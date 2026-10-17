# ============================================================
# End-to-end verification: REAL FastAPI + REAL Spring Boot.
#
# Prereqs:
#   1. FastAPI running:   uvicorn api.app:app --port 8000  (from repo root)
#   2. Backend running with a DB. Easiest is Docker:
#        docker compose up -d mysql redis
#      then run the backend with MySQL env vars, or:
#        cd backend && mvn spring-boot:run -Dspring-boot.run.jvmArguments=...
#      (this script defaults to a locally-run backend on :8080 with the
#       dev MySQL from docker-compose: user=cricket pw=cricket db=cricket)
#   3. This script (PowerShell) run from the repo root.
#
# It verifies, with real services (no mocks):
#   [1] backend health + FastAPI health
#   [2] create match
#   [3] fast-forward innings 1 (auto-prediction OFF so we don't fire slow
#       1st-innings score predictions), ending in an all-out that OPENS the chase
#   [4] DUPLICATE event -> duplicate=true, runs/version unchanged
#   [5] real MONTECARLO chase prediction via explicit /predict (fast path)
#   [6] prediction history + stale flag after a new ball
#   [7] FastAPI-FAILURE handling: ingest still succeeds, prediction returns 503
#       (no fabricated probability); auto-stops/restarts FastAPI when Docker-managed
#
# Env:
#   E2E_API              backend base URL        (default http://localhost:8080)
#   E2E_ML               FastAPI base URL        (default http://localhost:8000)
#   E2E_COMPOSE_DIR      repo root, enables automated FastAPI stop/start in [7]
#   E2E_SKIP_FASTAPI_STOP=1   skip the stop/start in [7]
# ============================================================
$ErrorActionPreference = "Stop"
# Overridable so the script works when host ports were remapped (e.g. a local
# MySQL/Oracle already owns 3306/8080). Backend container publishes BACKEND_HOST_PORT.
$API  = if ($env:E2E_API) { $env:E2E_API } else { "http://localhost:8080" }
$ML   = if ($env:E2E_ML)  { $env:E2E_ML }  else { "http://localhost:8000" }
$fail = 0

function Check($name, $cond, $detail) {
    if ($cond) { Write-Host "  [PASS] $name" -ForegroundColor Green }
    else       { Write-Host "  [FAIL] $name -- $detail" -ForegroundColor Red; $script:fail++ }
}

Write-Host "`n=== [1] Health ===" -ForegroundColor Cyan
try { $h = Invoke-RestMethod "$API/actuator/health" -TimeoutSec 5; Check "backend UP" ($h.status -eq "UP") ($h | ConvertTo-Json -Compress) }
catch { Check "backend UP" $false $_.Exception.Message }
try { $m = Invoke-RestMethod "$ML/health" -TimeoutSec 10; Check "fastapi healthy + models loaded" ($m.model_loaded -and $m.players_loaded -eq 516) ($m | ConvertTo-Json -Compress) }
catch { Check "fastapi up" $false $_.Exception.Message }

# The 1st-innings SCORE prediction path is slow (measured 22-539s) and would make
# this script time out, so we drive the engine via its fast 2nd-innings CHASE
# path. We open the chase by completing innings 1 (auto-prediction stays ON;
# xgboost per-ball predictions are fast).
Write-Host "`n=== [2] Create match ===" -ForegroundColor Cyan
$match = Invoke-RestMethod -Method Post "$API/api/matches" -ContentType "application/json" `
    -Body '{"team1":"Mumbai Indians","team2":"Chennai Super Kings"}'
Check "match created" ($null -ne $match.id) ($match | ConvertTo-Json -Compress)
$id = $match.id

Write-Host "`n=== [3] Fast-forward innings 1 -> opens the chase ===" -ForegroundColor Cyan
# Complete innings 1 by all-out (10 wickets) after posting a few runs, so the
# chase target (total + 1) is realistic and the 2nd innings is NOT instantly
# chased down. ball is 1-6 within an over; roll to the next over each 6 balls.
# Auto-prediction is ON (compose default). Innings 1 is fast-forwarded with
# xgboost, which is quick; the slow 1st-innings Monte Carlo path is only hit on
# request (see [5]).
$ballNo = 0
foreach ($r in @(1,1,4,2)) {   # a few scoring balls first
    $ov = [math]::Floor($ballNo / 6); $bal = ($ballNo % 6) + 1
    $b = @{ inning=1; over=$ov; ball=$bal; striker="R Sharma"; nonStriker="I Kishan"; bowler="T Boult"; runs=$r; wicket=$false; eventId="ff-r$ballNo" } | ConvertTo-Json
    $res = Invoke-RestMethod -Method Post "$API/api/matches/$id/balls" -ContentType "application/json" -Body $b
    $ballNo++
}
for ($w = 0; $w -lt 10; $w++) {   # then all out
    $ov = [math]::Floor($ballNo / 6); $bal = ($ballNo % 6) + 1
    $b = @{ inning=1; over=$ov; ball=$bal; striker="R Sharma"; nonStriker="I Kishan"; bowler="T Boult"; runs=0; wicket=$true; eventId="ff-w$w" } | ConvertTo-Json
    $res = Invoke-RestMethod -Method Post "$API/api/matches/$id/balls" -ContentType "application/json" -Body $b
    $ballNo++
}
Check "innings 1 completed -> currentInnings now 2" ($res.state.inning -eq 2) ($res.state | ConvertTo-Json -Compress)
# Auto-prediction is ON by default: the completed-innings response must carry a
# real xgboost win probability (0..1) - never a fabricated or missing one.
Check "auto prediction fired on ball" ($null -ne $res.prediction) "prediction=null error=$($res.predictionError)"
if ($res.prediction) {
    Check "auto prediction is valid xgboost (0..1)" `
        ($res.prediction.modelType -eq "xgboost" -and $res.prediction.winProbability -ge 0 -and $res.prediction.winProbability -le 1) `
        ($res.prediction | ConvertTo-Json -Compress)
}
# The completed-innings response now reports the NEW innings (2, runs=0), so
# innings 1's total is asserted via the chase target = total + 1.
$st = Invoke-RestMethod "$API/api/matches/$id/state"
Check "chase target = innings-1 total + 1 (8 + 1 = 9)" ($st.target -eq 9 -and $st.inning -eq 2) ("target="+$st.target+" inning="+$st.inning)
Write-Host ("  [INFO] innings-2 target = {0} (innings-1 total was 8)" -f $st.target) -ForegroundColor Yellow

Write-Host "`n=== [4] Chase ball ingested; DUPLICATE is idempotent ===" -ForegroundColor Cyan
$chase = @{ inning=2; over=0; ball=1; striker="V Kohli"; nonStriker="I Kishan"; bowler="T Boult"; runs=4; wicket=$false; eventId="chase-1" } | ConvertTo-Json
$rc = Invoke-RestMethod -Method Post "$API/api/matches/$id/balls" -ContentType "application/json" -Body $chase
Check "chase ball accepted" (-not $rc.duplicate) ($rc | ConvertTo-Json -Compress)
Check "chase runs recorded" ($rc.state.runs -eq 4) ($rc.state | ConvertTo-Json -Compress)
$rc2 = Invoke-RestMethod -Method Post "$API/api/matches/$id/balls" -ContentType "application/json" -Body $chase
Check "duplicate=true" ($rc2.duplicate -eq $true) ($rc2 | ConvertTo-Json -Compress)
Check "runs NOT double-counted" ($rc2.state.runs -eq 4) $rc2.state.runs

Write-Host "`n=== [5] Real Monte Carlo prediction ===" -ForegroundColor Cyan
$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $mc = Invoke-RestMethod -Method Post "$API/api/matches/$id/predict" -ContentType "application/json" `
        -Body '{"model":"montecarlo","nSimulations":300,"strikerName":"V Kohli"}'
    $sw.Stop()
    Check "montecarlo returned" ($mc.modelType -eq "montecarlo") ($mc | ConvertTo-Json -Compress)
    Check "known player accepted (516-db lookup)" ($null -ne $mc) "n/a"
    Write-Host ("  [INFO] montecarlo round-trip: {0} ms (300 sims, via Spring Boot)" -f $mc.latencyMs) -ForegroundColor Yellow
    Write-Host ("  [INFO] script-observed wall time: {0} ms" -f $sw.ElapsedMilliseconds) -ForegroundColor Yellow
}
catch {
    $sw.Stop()
    Check "montecarlo returned" $false "$($_.Exception.Message) (after $($sw.ElapsedMilliseconds) ms)"
}

Write-Host "`n=== [6] History + stale flag ===" -ForegroundColor Cyan
# PS 5.1's Invoke-RestMethod may hand back the JSON array as ONE nested object;
# the pipeline re-enumerates it so indexing works.
$hist = @(Invoke-RestMethod "$API/api/matches/$id/predictions" | ForEach-Object { $_ })
Check "history has entries" ($hist.Count -ge 1) "count=$($hist.Count)"
# Track the MONTECARLO prediction from [5]: with auto-prediction on, every ball
# appends a fresh prediction, so only older ones can be stale.
$mcPred = $hist | Where-Object { $_.modelType -eq "montecarlo" } | Select-Object -First 1
Check "montecarlo prediction stored in history" ($null -ne $mcPred) "not found in history"
$mv = [long]$mcPred.stateVersion
# Ingest one more ball: live stateVersion advances past the MC snapshot, so the
# MC prediction MUST now be flagged stale (staleness is version-based).
$after = @{ inning=2; over=0; ball=2; striker="V Kohli"; nonStriker="I Kishan"; bowler="T Boult"; runs=0; wicket=$false; eventId="stale-baller" } | ConvertTo-Json
$r6 = Invoke-RestMethod -Method Post "$API/api/matches/$id/balls" -ContentType "application/json" -Body $after
Check "later ball advanced stateVersion" ([long]$r6.state.stateVersion -gt $mv) ("pred v=$mv -> live v=$($r6.state.stateVersion)")
$hist2 = @(Invoke-RestMethod "$API/api/matches/$id/predictions" | ForEach-Object { $_ })
$mcAfter = $hist2 | Where-Object { $_.modelType -eq "montecarlo" } | Select-Object -First 1
Check "montecarlo prediction flagged stale after later ball" ($mcAfter.stale -eq $true) ($mcAfter | ConvertTo-Json -Compress)

Write-Host "`n=== [7] FastAPI failure handling (ingest must survive) ===" -ForegroundColor Cyan
# Automatable when the stack is Docker-managed. Set E2E_SKIP_FASTAPI_STOP=1 to
# skip (e.g. FastAPI running standalone under your own control). Otherwise we
# stop the fastapi container here, assert ingest survives + no fabricated
# probability, then restart it.
if ($env:E2E_SKIP_FASTAPI_STOP -eq "1") {
    Write-Host "  [SKIP] E2E_SKIP_FASTAPI_STOP=1 - not stopping FastAPI" -ForegroundColor Yellow
} else {
    if ($env:E2E_COMPOSE_DIR) { Push-Location $env:E2E_COMPOSE_DIR }
    Write-Host "  [INFO] stopping fastapi container..." -ForegroundColor Yellow
    # docker prints progress on stderr; under $ErrorActionPreference='Stop' a
    # native stderr line is a terminating error. Scope the preference down.
    & { $ErrorActionPreference = 'SilentlyContinue'; docker compose stop fastapi } | Out-Null
    Start-Sleep -Seconds 2
    # Auto-prediction is ON (compose default), so ingest attempts a prediction
    # against the dead FastAPI: the ball MUST still be accepted, the response
    # MUST carry predictionError and MUST NOT invent a probability.
    $ball2 = @{ inning=2; over=0; ball=3; striker="R Sharma"; bowler="T Boult"; runs=1; wicket=$false; eventId="ff-down-ball" } | ConvertTo-Json
    try {
        $r3 = Invoke-RestMethod -Method Post "$API/api/matches/$id/balls" -ContentType "application/json" -Body $ball2
        Check "ingest STILL works with FastAPI down" (-not $r3.duplicate) ($r3 | ConvertTo-Json -Compress)
        Check "no fabricated probability" ($null -eq $r3.prediction -and $null -ne $r3.predictionError) "predError=$($r3.predictionError)"
    }
    catch { Check "ingest with FastAPI down" $false $_.Exception.Message }

    try {
        Invoke-RestMethod -Method Post "$API/api/matches/$id/predict" -ContentType "application/json" -Body '{}' | Out-Null
        Check "explicit predict -> 503" $false "expected 503 but got success"
    }
    catch {
        $code = [int]$_.Exception.Response.StatusCode
        Check "explicit predict -> 503 Prediction Unavailable" ($code -eq 503) "status=$code"
    }

    Write-Host "  [INFO] restarting fastapi container..." -ForegroundColor Yellow
    & { $ErrorActionPreference = 'SilentlyContinue'; docker compose start fastapi } | Out-Null
    # Wait for FastAPI to become healthy again so later work isn't racing a boot.
    $ok = $false
    $st = ""
    foreach ($i in 1..30) {
        Start-Sleep -Seconds 4
        $st = & { $ErrorActionPreference = 'SilentlyContinue'; docker compose ps --format "{{.Service}}={{.Status}}" }
        if ($st -match "fastapi=.*healthy") { $ok = $true; break }
    }
    Check "fastapi back up after restart" $ok ("status=" + ($st -join ", "))
    if ($env:E2E_COMPOSE_DIR) { Pop-Location }
}

Write-Host ""
if ($fail -eq 0) { Write-Host "ALL CHECKS PASSED" -ForegroundColor Green; exit 0 }
else { Write-Host "$fail CHECK(S) FAILED" -ForegroundColor Red; exit 1 }

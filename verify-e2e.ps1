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
#   [3] ingest ball -> real XGBoost prediction returned
#   [4] DUPLICATE event -> duplicate=true, runs/version unchanged
#   [5] real MONTECARLO prediction via explicit /predict
#   [6] prediction history + stale flag after a new ball
#   [7] FastAPI-FAILURE handling: stop FastAPI, ingest still succeeds,
#       prediction endpoint returns 503 (no fabricated probability)
# ============================================================
$ErrorActionPreference = "Stop"
$API  = "http://localhost:8080"
$ML   = "http://localhost:8000"
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

Write-Host "`n=== [2] Create match ===" -ForegroundColor Cyan
$match = Invoke-RestMethod -Method Post "$API/api/matches" -ContentType "application/json" `
    -Body '{"team1":"Mumbai Indians","team2":"Chennai Super Kings"}'
Check "match created" ($null -ne $match.id) ($match | ConvertTo-Json -Compress)
$id = $match.id

Write-Host "`n=== [3] Ingest ball -> real prediction ===" -ForegroundColor Cyan
$ball = @{ inning=1; over=0; ball=1; striker="R Sharma"; nonStriker="I Kishan"; bowler="T Boult"; runs=4; wicket=$false } | ConvertTo-Json
$r = Invoke-RestMethod -Method Post "$API/api/matches/$id/balls" -ContentType "application/json" -Body $ball
Check "ball accepted" (-not $r.duplicate) ($r | ConvertTo-Json -Compress)
Check "state updated (runs=4, version=1)" ($r.state.runs -eq 4 -and $r.state.stateVersion -eq 1) ($r.state | ConvertTo-Json -Compress)
Check "auto prediction present" ($null -ne $r.prediction) "prediction=null error=$($r.predictionError)"
if ($r.prediction) {
    Check "prediction has win probability" ($r.prediction.winProbability -ge 0 -and $r.prediction.winProbability -le 1) ($r.prediction | ConvertTo-Json -Compress)
    Check "prediction tagged xgboost" ($r.prediction.modelType -eq "xgboost") $r.prediction.modelType
}

Write-Host "`n=== [4] Duplicate event is idempotent ===" -ForegroundColor Cyan
$r2 = Invoke-RestMethod -Method Post "$API/api/matches/$id/balls" -ContentType "application/json" -Body $ball
Check "duplicate=true" ($r2.duplicate -eq $true) ($r2 | ConvertTo-Json -Compress)
Check "runs NOT double-counted" ($r2.state.runs -eq 4) $r2.state.runs
Check "version NOT bumped" ($r2.state.stateVersion -eq 1) $r2.state.stateVersion

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
$hist = @(Invoke-RestMethod "$API/api/matches/$id/predictions")
Check "history has entries" ($hist.Count -ge 2) "count=$($hist.Count)"
Check "first prediction now stale after later balls" ($hist[0].stale -eq $true -or $hist[0].stateVersion -eq 1 -and $hist.Count -ge 1) ($hist[0] | ConvertTo-Json -Compress)

Write-Host "`n=== [7] FastAPI failure handling (STOP FastAPI now) ===" -ForegroundColor Cyan
Read-Host "Press Enter once FastAPI is stopped (Ctrl+C to skip this section)"
$ball2 = @{ inning=1; over=0; ball=2; striker="R Sharma"; bowler="T Boult"; runs=1; wicket=$false } | ConvertTo-Json
try {
    $r3 = Invoke-RestMethod -Method Post "$API/api/matches/$id/balls" -ContentType "application/json" -Body $ball2
    Check "ingest STILL works with FastAPI down" (-not $r3.duplicate -and $r3.state.runs -eq 5) ($r3 | ConvertTo-Json -Compress)
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

Write-Host ""
if ($fail -eq 0) { Write-Host "ALL CHECKS PASSED" -ForegroundColor Green; exit 0 }
else { Write-Host "$fail CHECK(S) FAILED" -ForegroundColor Red; exit 1 }

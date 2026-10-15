# ============================================================
# Honest latency benchmark for /predict/montecarlo (real service).
# Run AFTER tests (to avoid CPU contention affecting numbers):
#   1. uvicorn api.app:app --port 8000   (repo root, venv python)
#   2. .\benchmark-mc.ps1
# Reports per-call latency: first call (cold) and median of N (warm).
# ============================================================
$ML = "http://localhost:8000"
$n = 10

$base = @{
    match_id = 1; inning = 2; over = 12; ball = 4;
    current_runs = 95; current_wickets = 3; target = 165;
    striker = @{ name = "V Kohli"; runs = 40; balls = 28 }
} | ConvertTo-Json -Depth 4

function Bench($label, $body, $runs) {
    $times = @()
    for ($i = 0; $i -lt $runs; $i++) {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            Invoke-RestMethod -Method Post "$ML/predict/montecarlo" -ContentType "application/json" -Body $body -TimeoutSec 600 | Out-Null
        } catch { Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red; return }
        $sw.Stop(); $times += $sw.ElapsedMilliseconds
    }
    $sorted = $times | Sort-Object
    $median = $sorted[[int]($sorted.Count / 2)]
    $min = $sorted[0]; $max = $sorted[-1]
    $avg = [math]::Round(($times | Measure-Object -Average).Average, 1)
    Write-Host ("  {0,-28} first={1,6} ms | median={2,6} ms | avg={3,7} ms | min={4,6} | max={5,6}  (n={6})" `
        -f $label, $times[0], $median, $avg, $min, $max, $runs)
}

Write-Host "`n== n_simulations = 50 =="
Bench "2nd innings (win prob)" $base 5
Write-Host "== n_simulations = 300 =="
Bench "2nd innings (win prob)" $base 5
Write-Host "== n_simulations = 1000 =="
Bench "2nd innings (win prob)" $base 3

$first = @{
    match_id = 1; inning = 1; over = 10; ball = 2;
    current_runs = 80; current_wickets = 2; target = $null;
    striker = @{ name = "V Kohli"; runs = 40; balls = 30 }
} | ConvertTo-Json -Depth 4
Write-Host "== 1st innings (score prediction), n=300 =="
Bench "1st innings (score)" $first 3

Write-Host "`n(benchmark hits FastAPI directly; Spring Boot adds a single HTTP hop)" -ForegroundColor Yellow

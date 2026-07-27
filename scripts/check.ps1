param(
    [switch]$Fix,
    [string]$Python = ""
)

$repository = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $Python = Join-Path $repository ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python environment not found: $Python. Create .venv and install .[dev] first."
}
$ruff = Join-Path (Split-Path -Parent $Python) "ruff.exe"
if (-not (Test-Path -LiteralPath $ruff -PathType Leaf)) {
    throw "Ruff not found: $ruff. Install the pinned .[dev] dependencies first."
}

Push-Location $repository
try {
    $env:PYTHONPATH = Join-Path $repository "src"
    if ($Fix) {
        & $ruff check src tests --fix
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $ruff format src tests
    }
    else {
        & $ruff format --check src tests
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $ruff check src tests
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m unittest discover -s tests -v
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

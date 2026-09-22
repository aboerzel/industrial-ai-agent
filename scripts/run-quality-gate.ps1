[CmdletBinding()]
param(
    [ValidateSet("FAST", "INTEGRATION")]
    [string]$Tier
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Configured project Python executable was not found: $Python"
}

Push-Location $ProjectRoot
try {
    if ($Tier -eq "FAST") {
        & $Python -m pytest tests/unit
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        Push-Location (Join-Path $ProjectRoot "frontend")
        try {
            npm run test
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        finally {
            Pop-Location
        }

        & $Python -m ruff check src tests scripts
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $Python -m ruff format --check src tests scripts
        exit $LASTEXITCODE
    }

    if (-not $env:FACTORY_DATABASE_ADMIN_URL) {
        Write-Output "SKIPPED / INFRASTRUCTURE_UNAVAILABLE: FACTORY_DATABASE_ADMIN_URL is not configured."
        exit 0
    }

    & $Python -m pytest tests/integration
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

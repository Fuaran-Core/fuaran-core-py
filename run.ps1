#Requires -Version 7.0
# fuaran-core-py: the one-command entry point.
# ruff format --check -> ruff check -> pytest.
# Uses .venv when present (create it with: python -m venv .venv; .venv/Scripts/python -m pip install -e ".[dev]").
# Switches: -SkipFormat / -SkipLint / -SkipTests for fast iteration.
[CmdletBinding()]
param(
    [switch]$SkipFormat,
    [switch]$SkipLint,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Resolve-Python {
    $venv = if ($IsWindows) { Join-Path $PSScriptRoot ".venv/Scripts/python.exe" } else { Join-Path $PSScriptRoot ".venv/bin/python" }
    if (Test-Path $venv) { return $venv }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { return $cmd.Source }
    }
    throw "Python 3.12 or later is required but no interpreter was found (no .venv, no python on PATH)."
}

function Invoke-Stage {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "==> $Name"
    $global:LASTEXITCODE = 0
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
}

$py = Resolve-Python
$env:PYTHONPATH = (Join-Path $PSScriptRoot "src")

if (-not $SkipFormat) { Invoke-Stage "ruff format --check" { & $py -m ruff format --check . } }
if (-not $SkipLint) { Invoke-Stage "ruff check" { & $py -m ruff check . } }
if (-not $SkipTests) { Invoke-Stage "pytest" { & $py -m pytest -q } }

Write-Host "fuaran-core-py: green"
exit 0

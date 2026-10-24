#Requires -Version 7.0
# fuaran-core-py: the one-command entry point.
# ruff format --check -> ruff check -> the reference's oracle built -> pytest.
#
# pytest includes the conformance legs (tests/), which read the reference's vectors from a Core
# checkout: FUARAN_CORE_DIR, or `fuaran-core/` beside this repository, at the commit
# core-pin.json names. They FAIL when no checkout is found rather than skip, because a skipped
# leg certifies nothing. The oracle differential in the same suite drives the reference's oracle
# process, built here from that checkout (tools/Fuaran.Core.Oracle.Cli) unless
# FUARAN_CORE_ORACLE names a command line that serves the protocol; it too fails rather than
# skips. The differential's bounded run (its seed and example count, tests/test_oracle_differential.py)
# is part of every pytest, so the gate's run is the run host-compliance.json declares.
#
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

# The Core checkout the legs read: FUARAN_CORE_DIR, or fuaran-core/ beside this repository or an
# ancestor of it. Resolved here so the oracle can be built from it; the legs resolve it the same way.
function Find-Core {
    if ($env:FUARAN_CORE_DIR) { return $env:FUARAN_CORE_DIR }
    $dir = Split-Path -Parent $PSScriptRoot
    while ($dir) {
        $candidate = Join-Path $dir "fuaran-core"
        if (Test-Path (Join-Path $candidate "conformance/apply/manifest.json")) { return $candidate }
        $parent = Split-Path -Parent $dir
        if ($parent -eq $dir) { break }
        $dir = $parent
    }
    return $null
}

$py = Resolve-Python
$env:PYTHONPATH = (Join-Path $PSScriptRoot "src")

if (-not $SkipFormat) { Invoke-Stage "ruff format --check" { & $py -m ruff format --check . } }
if (-not $SkipLint) { Invoke-Stage "ruff check" { & $py -m ruff check . } }
if (-not $SkipTests) {
    $core = Find-Core
    if (-not $core) {
        Write-Host "FAILED: no Core checkout: clone https://github.com/Fuaran-Core/fuaran-core beside this repository (as fuaran-core/) at the commit core-pin.json names, or set FUARAN_CORE_DIR"
        exit 1
    }
    $env:FUARAN_CORE_DIR = $core
    if (-not $env:FUARAN_CORE_ORACLE) {
        # The oracle process the differential drives, built from the checkout the vectors are read
        # from, so both halves of the certification name one Core commit.
        Invoke-Stage "dotnet build (the reference's oracle, from $core)" {
            $dotnet = Get-Command dotnet -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $dotnet) {
                Write-Host "the .NET SDK is required to build the reference's oracle; or set FUARAN_CORE_ORACLE to a command line that serves the protocol"
                $global:LASTEXITCODE = 1
                return
            }
            & $dotnet.Source build (Join-Path $core "tools/Fuaran.Core.Oracle.Cli/Fuaran.Core.Oracle.Cli.fsproj") -c Release --nologo -v q
        }
    }
    Invoke-Stage "pytest" { & $py -m pytest -q -p no:cacheprovider }
}

Write-Host "fuaran-core-py: green"
exit 0

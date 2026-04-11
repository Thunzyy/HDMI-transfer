[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipNativeLoopback
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string[]]$Command
    )

    Write-Host ""
    Write-Host "==> $Name"
    Write-Host ("    " + ($Command -join " "))

    if ($Command.Count -gt 1) {
        & $Command[0] @($Command[1..($Command.Count - 1)])
    } else {
        & $Command[0]
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name"
    }
}

Push-Location $RepoRoot
try {
    $pytestCommand = @($Python, "-m", "pytest", "-m", "not hardware")
    if ($SkipNativeLoopback) {
        $pytestCommand += @("--ignore", "tests/test_loopback.py")
    }

    Invoke-Step -Name "Non-hardware pytest suite" -Command $pytestCommand
    Invoke-Step -Name "Fountain overhead gates" -Command @(
        $Python,
        "-m",
        "pytest",
        "tests/test_fountain_overhead.py",
        "tests/perf/test_fountain_budget.py",
        "-v"
    )
    Invoke-Step -Name "Browser sender asset drift check" -Command @(
        $Python,
        "tools/build_sender_html.py",
        "--check"
    )

    $benchCommand = Get-Command "hdmi-bench" -ErrorAction SilentlyContinue
    if ($null -ne $benchCommand) {
        Invoke-Step -Name "Benchmark smoke" -Command @(
            $benchCommand.Source,
            "--profile",
            "balanced",
            "--mode",
            "fountain",
            "--no-json"
        )
    } else {
        Invoke-Step -Name "Benchmark smoke" -Command @(
            $Python,
            "-m",
            "hdmi_exfil.core.cli.benchmark",
            "--profile",
            "balanced",
            "--mode",
            "fountain",
            "--no-json"
        )
    }
} finally {
    Pop-Location
}

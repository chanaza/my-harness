# my-harness installer for Windows.
#   irm https://raw.githubusercontent.com/chanaza/my-harness/main/scripts/install.ps1 | iex
# Checks Python and Git, installs (or updates) the engine, then runs the guided setup.
# Installs CAPTURE only: nothing from your harness is loaded into your tools.

$ErrorActionPreference = "Stop"
$engine = if ($env:HARNESS_ENGINE_URL) { $env:HARNESS_ENGINE_URL } else { "git+https://github.com/chanaza/my-harness" }

function Find-Python {
    foreach ($candidate in @("python", "py")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            $version = & $candidate -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
            if ($version -eq "True") { return $candidate }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.11 or newer is needed." -ForegroundColor Yellow
    Write-Host "Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again."
    return
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is needed." -ForegroundColor Yellow
    Write-Host "Install it from https://git-scm.com/download/win, then run this again."
    return
}

Write-Host "Installing my-harness..."
& $python -m pip install --user --quiet --upgrade $engine
if ($LASTEXITCODE -ne 0) { Write-Host "Installation failed (see above)." -ForegroundColor Red; return }

& $python -m harness setup @args

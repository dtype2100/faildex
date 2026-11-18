# faildex installer for Windows (PowerShell 5.1 or 7).
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/dtype2100/faildex/main/install.ps1 | iex"
#
# What it does: installs uv (https://docs.astral.sh/uv/) if it is missing, then
# installs the `faildex` command with `uv tool install`. Nothing else is changed.
# It installs from the GitHub archive, so git is not needed.
# Set FAILDEX_SOURCE to install from somewhere else (a folder, a wheel, a git URL).

$ErrorActionPreference = "Stop"
$source = if ($env:FAILDEX_SOURCE) { $env:FAILDEX_SOURCE } else { "https://github.com/dtype2100/faildex/archive/refs/heads/main.zip" }

# PowerShell does not stop on a failing external program, so check each one.
function Fail($what) { Write-Host "faildex: $what failed (exit $LASTEXITCODE); nothing more was changed." -ForegroundColor Red; exit 1 }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "faildex: installing uv first"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) { Fail "installing uv" }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Fail "finding uv after installing it" }
}

Write-Host "faildex: installing from $source"
uv tool install --force $source
if ($LASTEXITCODE -ne 0) { Fail "uv tool install" }
uv tool update-shell | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "faildex: could not add uv's tool folder to PATH; run 'uv tool update-shell' yourself." }

Write-Host ""
Write-Host "faildex is installed. Open a new terminal, then try:"
Write-Host "  faildex demo                 # rules, a pre-run warning and the numbers, on public logs"
Write-Host "  faildex check `"git status`"   # what is known to go wrong with a command"

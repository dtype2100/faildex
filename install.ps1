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

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "faildex: installing uv first"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "faildex: installing from $source"
uv tool install --force $source
uv tool update-shell | Out-Null

Write-Host ""
Write-Host "faildex is installed. Open a new terminal, then try:"
Write-Host "  faildex demo                 # rules, a pre-run warning and the numbers, on public logs"
Write-Host "  faildex check `"git status`"   # what is known to go wrong with a command"

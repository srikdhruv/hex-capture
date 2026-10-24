# One-command launcher for the Blueprints bot (Windows):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.ps1 | iex"
# Play against the engine locally (no account/token):
#   powershell -ExecutionPolicy Bypass -c "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.ps1))) --play"
# Downloads hexbot-windows-x64.exe into %USERPROFILE%\.hexbot\ (re-downloads when a newer release exists) and runs it.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$Base = 'https://github.com/srikdhruv/hex-capture/releases/download/latest'
$Dir = Join-Path $env:USERPROFILE '.hexbot'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$Asset = 'hexbot-windows-x64.exe'
$Bin = Join-Path $Dir $Asset

# Always run the newest build: compare the release sha with what the local exe reports.
$remote = ''
try { $remote = ((Invoke-RestMethod -UseBasicParsing "$Base/version.txt?t=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())").ToString().Trim() -split '\s+')[0] } catch { }
$localV = ''
if (Test-Path $Bin) { try { $localV = ((& $Bin --version) | Select-Object -First 1).ToString().Trim() } catch { } }
if (-not (Test-Path $Bin) -or ($remote -and $remote -ne $localV)) {
  Write-Host "Downloading $Asset $remote ..."
  Invoke-WebRequest -UseBasicParsing -Uri "$Base/$Asset" -OutFile "$Bin.part"
  Move-Item -Force "$Bin.part" $Bin
}
Unblock-File -Path $Bin -ErrorAction SilentlyContinue
Remove-Item -Force -ErrorAction SilentlyContinue "$Bin.old"
Write-Host "Starting hexbot (Ctrl+C to stop). Logs: $Dir\logs"
& $Bin @args

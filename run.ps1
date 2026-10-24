# One-command launcher for the Blueprints bot (Windows):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.ps1 | iex"
# Downloads hexbot-windows-x64.exe into %USERPROFILE%\.hexbot\ (re-downloads when a newer release exists) and runs it.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$Base = 'https://github.com/srikdhruv/hex-capture/releases/download/latest'
$Dir = Join-Path $env:USERPROFILE '.hexbot'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$Asset = 'hexbot-windows-x64.exe'
$Bin = Join-Path $Dir $Asset
$VerFile = Join-Path $Dir "$Asset.version"

$remote = ''
try { $remote = (Invoke-RestMethod -UseBasicParsing "$Base/version.txt").ToString().Trim() } catch { }
$localV = ''
if (Test-Path $VerFile) { $localV = (Get-Content $VerFile -Raw).Trim() }
if (-not (Test-Path $Bin) -or ($remote -and $remote -ne $localV)) {
  Write-Host "Downloading $Asset $remote ..."
  Invoke-WebRequest -UseBasicParsing -Uri "$Base/$Asset" -OutFile "$Bin.part"
  Move-Item -Force "$Bin.part" $Bin
  if ($remote) { Set-Content -Path $VerFile -Value $remote }
}
Unblock-File -Path $Bin -ErrorAction SilentlyContinue
Write-Host "Starting hexbot (Ctrl+C to stop). Logs: $Dir\logs"
& $Bin @args

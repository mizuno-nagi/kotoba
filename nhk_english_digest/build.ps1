$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Venv314 = Join-Path $Root ".venv314\Scripts\python.exe"

if (-not (Test-Path $Venv314)) {
    throw "Virtual environment not found. Run: python -m venv .venv314"
}

# Keep the script ASCII-only so Windows PowerShell 5.1 reads it correctly.
$AppName = [string][char]0x8A00 + [string][char]0x53F6

$Dist = Join-Path $Root ("dist\" + $AppName)
$DistConfig = Join-Path $Dist "config.yaml"
$DistSecret = Join-Path $Dist "secret_store.json"
$ConfigBackup = Join-Path $Root "config.dist.backup.yaml"
$SecretBackup = Join-Path $Root "secret_store.dist.backup.json"
if (Test-Path $DistConfig) {
    Copy-Item -Force $DistConfig $ConfigBackup
}
if (Test-Path $DistSecret) {
    Copy-Item -Force $DistSecret $SecretBackup
}

& $Venv314 -m pip install -r (Join-Path $Root "requirements.txt") pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed"
}

Set-Location $Root
& $Venv314 -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --collect-all customtkinter `
    --icon (Join-Path $Root "assets\app.ico") `
    --add-data ((Join-Path $Root "assets") + ";assets") `
    --name $AppName `
    --distpath (Join-Path $Root "dist") `
    --workpath (Join-Path $Root "build") `
    "desktop_app.py"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

if (Test-Path $ConfigBackup) {
    Copy-Item -Force $ConfigBackup $DistConfig
    Remove-Item -Force $ConfigBackup
} else {
    Copy-Item -Force (Join-Path $Root "config.template.yaml") $DistConfig
}
if (Test-Path $SecretBackup) {
    Copy-Item -Force $SecretBackup $DistSecret
    Remove-Item -Force $SecretBackup
} elseif (Test-Path (Join-Path $Root "secret_store.json")) {
    Copy-Item -Force (Join-Path $Root "secret_store.json") $DistSecret
}
Copy-Item -Force (Join-Path $Root "VERSION") (Join-Path $Dist "VERSION")
New-Item -ItemType Directory -Force (Join-Path $Dist "output") | Out-Null
Copy-Item -Force (Join-Path $Root "README.md") (Join-Path $Dist "README.md")

$Exe = Join-Path $Dist ($AppName + ".exe")
$Smoke = Start-Process `
    -FilePath $Exe `
    -ArgumentList "--smoke-test" `
    -Wait `
    -PassThru
if ($Smoke.ExitCode -ne 0) {
    throw "Smoke test failed with exit code $($Smoke.ExitCode)"
}

Write-Host ""
Write-Host "Build complete: $Dist"
Write-Host "Copy the whole '$AppName' folder to another Windows PC and run the exe."

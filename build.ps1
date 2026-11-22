# Builds dist\ClipCa (the app) and Output\ClipCa-Setup-<version>.exe (the installer to share).
# Needs: venv with vosk, sounddevice, obsws-python, pystray, pillow, pyinstaller; Inno Setup 6.
Set-Location $PSScriptRoot
$py = ".\venv\Scripts\python.exe"
# Offline speech models (Apache-2.0), fetched once: too big for git.
foreach ($m in 'vosk-model-small-fr-0.22', 'vosk-model-small-en-us-0.15') {
    if (-not (Test-Path "models\$m")) {
        New-Item -ItemType Directory -Force models | Out-Null
        Invoke-WebRequest "https://alphacephei.com/vosk/models/$m.zip" -OutFile "models\$m.zip"
        Expand-Archive "models\$m.zip" -DestinationPath models -Force
        Remove-Item "models\$m.zip"
    }
}
& $py -m PyInstaller --noconfirm --clean --windowed --name ClipCa --icon icon.ico `
    --add-data "models;models" --add-data "icon.png;." --add-data "icon.ico;." `
    --collect-all vosk --collect-all sounddevice --hidden-import pystray._win32 clipper_app.py
if ($LASTEXITCODE) { throw "PyInstaller failed" }
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
& $iscc /Q installer.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }
Get-ChildItem Output\*.exe

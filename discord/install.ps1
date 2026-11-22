# Installs Vencord with the "Upload Last Clip" plugin into Discord, and keeps it installed after Discord updates.
# Needs Git and Node.js. Usage: powershell -ExecutionPolicy Bypass -File discord\install.ps1
param([string]$VencordDir = "$env:USERPROFILE\Apps\Vencord")
$ErrorActionPreference = 'Stop'

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { npm i -g pnpm }
if (-not (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*" -ErrorAction SilentlyContinue) -and
    -not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    winget install --id Gyan.FFmpeg -e --silent --accept-package-agreements --accept-source-agreements
}

if (-not (Test-Path $VencordDir)) { git clone https://github.com/Vendicated/Vencord.git $VencordDir }
Copy-Item "$PSScriptRoot\uploadLastClip" "$VencordDir\src\userplugins\" -Recurse -Force
Copy-Item "$PSScriptRoot\keep-vencord.ps1" $VencordDir -Force

Push-Location $VencordDir
try {
    pnpm install --frozen-lockfile
    pnpm build
    node scripts/runInstaller.mjs -- -install -branch stable  # closes Discord while it patches
} finally { Pop-Location }

# Turn the plugin on in Vencord's settings (Discord is closed by the installer at this point)
$settingsFile = "$env:APPDATA\Vencord\settings\settings.json"
$s = if (Test-Path $settingsFile) { Get-Content $settingsFile -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
if (-not $s.plugins) { $s | Add-Member plugins ([pscustomobject]@{}) -Force }
$s.plugins | Add-Member UploadLastClip ([pscustomobject]@{ enabled = $true; maxSizeMB = 10 }) -Force
New-Item (Split-Path $settingsFile) -ItemType Directory -Force | Out-Null
[IO.File]::WriteAllText($settingsFile, ($s | ConvertTo-Json -Depth 20))  # no BOM: Vencord's JSON.parse chokes on one

# Re-inject after Discord updates: at logon and every 5 minutes, hidden
$action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$VencordDir\keep-vencord.ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)).Repetition
$taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Keep Vencord' -Action $action -Trigger $trigger -Settings $taskSettings -Description 'Re-injects Vencord after Discord updates' -Force | Out-Null

Write-Host "Done. Open Discord, click + in a chat, then 'Upload Last Clip'."

# Re-injects Vencord when a Discord update installs a fresh, unpatched app-x.y.z folder.
# Run by the "Keep Vencord" scheduled task at logon and every 5 minutes.
$discord = "$env:LOCALAPPDATA\Discord"
$latest = Get-ChildItem $discord -Directory -Filter 'app-*' |
    Sort-Object { [version]($_.Name -replace '^app-') } | Select-Object -Last 1
if (-not $latest) { exit }
$res = Join-Path $latest.FullName 'resources'
if (-not (Test-Path "$res\app.asar") -or (Test-Path "$res\_app.asar")) { exit }  # already patched
if (Get-Process Update -ErrorAction SilentlyContinue | Where-Object Path -like "$discord\*") { exit }  # update still running, try next time

$wasRunning = [bool](Get-Process Discord -ErrorAction SilentlyContinue)
$env:VENCORD_USER_DATA_DIR = $PSScriptRoot
$env:VENCORD_DEV_INSTALL = '1'
"$(Get-Date -Format s) repatching $($latest.Name)" | Out-File "$PSScriptRoot\keep-vencord.log" -Append
& "$PSScriptRoot\dist\Installer\VencordInstallerCli.exe" -install -location $discord *>> "$PSScriptRoot\keep-vencord.log"
if ($wasRunning) { Start-Process "$discord\Update.exe" -ArgumentList '--processStart', 'Discord.exe' }

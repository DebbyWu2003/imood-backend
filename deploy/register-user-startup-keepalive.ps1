# Registers the WSL keepalive to run at logon, WITHOUT needing administrator.
#
#   powershell -ExecutionPolicy Bypass -File C:\imood_project\imood-voice\deploy\register-user-startup-keepalive.ps1
#
# Use this instead of register-windows-boot-task.ps1 when the account is a
# standard user: Register-ScheduledTask fails with "Access is denied" there,
# even at -RunLevel Limited for the calling user. The scheduled task triggered
# -AtLogOn anyway, so a Startup-folder entry fires at the same moment; what we
# give up is the task engine restarting a dead process, which wsl-keepalive.ps1
# does for itself with its own loop.
#
# To disable: open shell:startup and delete imood-wsl-keepalive.lnk

$ErrorActionPreference = "Stop"

$loop = Join-Path $PSScriptRoot "wsl-keepalive.ps1"
if (-not (Test-Path $loop)) { throw "keepalive script not found: $loop" }

$startup = [Environment]::GetFolderPath("Startup")
if (-not $startup) { throw "could not resolve the Startup folder" }
$lnk = Join-Path $startup "imood-wsl-keepalive.lnk"

$sh = New-Object -ComObject WScript.Shell
$s  = $sh.CreateShortcut($lnk)
$s.TargetPath       = (Get-Command powershell.exe).Source
$s.Arguments        = "-WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File `"$loop`""
$s.WorkingDirectory = $PSScriptRoot
$s.WindowStyle      = 7   # minimised; -WindowStyle Hidden does the real hiding
$s.Description      = "Hold a WSL2 client open so imood-tts stays up"
$s.Save()

if (-not (Test-Path $lnk)) { throw "shortcut was not created: $lnk" }
Write-Host "registered: $lnk"
Write-Host "starting it now so you do not have to log out and back in..."
Start-Process -FilePath $s.TargetPath -ArgumentList $s.Arguments -WindowStyle Hidden
Write-Host "done. verify with:  wsl -d Ubuntu-24.04 -u root -- systemctl is-active imood-tts"

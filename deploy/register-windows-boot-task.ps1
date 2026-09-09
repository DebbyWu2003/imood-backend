# Run once in an ELEVATED PowerShell (Run as administrator):
#   powershell -ExecutionPolicy Bypass -File C:\imood-backend\deploy\register-windows-boot-task.ps1
#
# Registers a logon task that holds a WSL2 client open (`tail -f /dev/null`),
# which keeps the Ubuntu-24.04 VM — and therefore the imood-tts systemd
# service — running from the moment you sign in. Without it, WSL only runs
# while a terminal is open and the service stops when the VM idles out.
#
# Pairs with %USERPROFILE%\.wslconfig (vmIdleTimeout=-1).
#
# Remove with:  Unregister-ScheduledTask -TaskName "imood-tts-wsl-keepalive" -Confirm:$false

$taskName = "imood-tts-wsl-keepalive"

$action  = New-ScheduledTaskAction -Execute "wsl.exe" `
             -Argument "-d Ubuntu-24.04 --exec /usr/bin/sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
             -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 `
             -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
  -Settings $set -Principal $principal `
  -Description "Hold a WSL2 client open so the imood-tts service stays up" -Force

Start-ScheduledTask -TaskName $taskName
Write-Host "`nRegistered and started. Check:  wsl -d Ubuntu-24.04 -u root -- systemctl status imood-tts"

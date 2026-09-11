# Holds a WSL2 client open so the shared WSL VM -- and therefore the systemd
# services inside its distros (imood-tts on :8001) -- stay up. WSL2 tears the
# VM down seconds after the last wsl.exe client exits, and .wslconfig
# vmIdleTimeout=-1 does not work on WSL 2.7.13, so something has to hold a
# client open for as long as you are logged in.
#
# Launched hidden at logon by register-user-startup-keepalive.ps1.
#
# The loop is deliberate: if the client dies (console event, `wsl --shutdown`,
# a WSL service restart) the VM would idle out and imood-tts would stop with
# it. Relaunching gives us what a scheduled task would have done with
# -RestartCount, which we cannot use because registering one needs admin.
param([string]$Distro = "Ubuntu-24.04")

while ($true) {
  # --exec with /usr/bin/sleep infinity, NOT `tail -f /dev/null`:
  # under --exec tail exits 1 immediately and the VM drops.
  Start-Process -Wait -NoNewWindow wsl.exe `
    -ArgumentList "-d", $Distro, "--exec", "/usr/bin/sleep", "infinity"
  Start-Sleep -Seconds 5
}

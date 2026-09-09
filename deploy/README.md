# imood-tts deployment (WSL2 + systemd)

Keeps the CosyVoice2 TTS service (`tts_service.py`, port 8001) running and
restarts it if it crashes. `server.py` on Windows talks to it over
`localhost:8001`; JoyGen will do the same.

## Files

| file | installed to | purpose |
|---|---|---|
| `imood-tts.service` | `/etc/systemd/system/` (WSL) | the service unit — `Restart=always` |
| `imood-tts.env` | `/etc/imood-tts.env` (WSL) | tunables: volume, voice, model paths |
| `install-wsl-tts-service.sh` | run in WSL | installs + enables + starts the above |
| `register-windows-boot-task.ps1` | run elevated on Windows | logon keepalive that holds WSL up |
| `../../.wslconfig` (`%USERPROFILE%\.wslconfig`) | — | `vmIdleTimeout=-1` so the VM doesn't idle out |

## Why the keepalive

`systemd=true` alone is **not** enough: WSL2 tears the VM down once the last
`wsl.exe` client exits, and systemd stops every service on the way down. So you
need both (a) `.wslconfig` `vmIdleTimeout=-1`, and (b) a logon task that keeps one
`wsl.exe` client attached. `register-windows-boot-task.ps1` sets up (b); (a) is a
plain file already at `%USERPROFILE%\.wslconfig` — run `wsl --shutdown` once to
apply it.

## Install

**1. Inside WSL** (Ubuntu-24.04), as root — needs `systemd=true` in `/etc/wsl.conf`:

```bash
sudo bash /mnt/c/imood-backend/deploy/install-wsl-tts-service.sh
```

**2. On Windows**, in an **elevated** PowerShell (once):

```powershell
wsl --shutdown   # picks up %USERPROFILE%\.wslconfig
powershell -ExecutionPolicy Bypass -File C:\imood-backend\deploy\register-windows-boot-task.ps1
```

## Operate (from WSL)

```bash
systemctl status imood-tts          # state
journalctl -u imood-tts -f          # live log  (or: tail -f /var/log/imood-tts.log)
sudo systemctl restart imood-tts    # after editing /etc/imood-tts.env
sudo systemctl stop imood-tts       # take it down
curl -s localhost:8001/health       # ready check (warm start ~40s)
```

From Windows you can drive the same thing without opening a WSL shell:

```
wsl -d Ubuntu-24.04 -u root -- systemctl restart imood-tts
wsl -d Ubuntu-24.04 -u root -- systemctl status imood-tts --no-pager
```

## Tuning

Edit `/etc/imood-tts.env`, then `sudo systemctl restart imood-tts`.

- **Volume** — `TTS_RMS_DBFS` (default `-14`; louder `-12`, quieter `-16`).
- **Voice** — uncomment `TTS_PROMPT_WAV` + `TTS_PROMPT_TEXT` and point them at a
  3–10 s reference clip and its exact transcript.

## Remove

```bash
sudo systemctl disable --now imood-tts && sudo rm /etc/systemd/system/imood-tts.service /etc/imood-tts.env
```
```powershell
Unregister-ScheduledTask -TaskName "imood-tts-wsl-keepalive" -Confirm:$false
# and delete %USERPROFILE%\.wslconfig if nothing else needs it
```

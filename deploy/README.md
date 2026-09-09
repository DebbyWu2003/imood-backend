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

## Why the keepalive (read this)

`systemd=true` alone is **not** enough. WSL2 powers the VM off a few seconds
after the last `wsl.exe` client exits — systemd stops every service, and because
the enabled `imood-tts` unit auto-starts on the next boot but takes ~50 s to warm
up (vLLM CUDA-graph capture), a machine with no attached client sits in a
restart death-spiral and never becomes usable.

There is no working `.wslconfig` knob for this on WSL 2.7 (`vmIdleTimeout=-1` has
no effect). The fix is to **keep one `wsl.exe` client attached at all times**:
`register-windows-boot-task.ps1` registers a logon task that runs
`wsl.exe -d Ubuntu-24.04 --exec /usr/bin/sleep infinity` forever.
(`tail -f /dev/null` exits 1 under `--exec` — must be `sleep`.)

Until you sign out/in after registering it, keep any WSL terminal window open.

## Install

**1. Inside WSL** (Ubuntu-24.04), as root — needs `systemd=true` in `/etc/wsl.conf`:

```bash
sudo bash /mnt/c/imood-backend/deploy/install-wsl-tts-service.sh
```

**2. On Windows**, in an **elevated** PowerShell (once):

```powershell
powershell -ExecutionPolicy Bypass -File C:\imood-backend\deploy\register-windows-boot-task.ps1
```

The script registers the task **and starts it now**. Confirm it stuck:

```powershell
Get-ScheduledTask imood-tts-wsl-keepalive | Get-ScheduledTaskInfo | Select LastTaskResult  # want 267009 = "still running"
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

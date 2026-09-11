# Runs the imood-voice Windows service (ASR + LLM + dialogue on :8000) and
# restarts it if it exits. Launched hidden at logon by
# register-user-startup-server.ps1.
#
# The working directory is NOT optional: server.py resolves the model as a
# relative path (MODEL_PATH = "./models/qwen2.5-1.5b-instruct-q4_k_m.gguf"),
# so starting it from anywhere else fails to load the LLM.
#
# There is no ordering constraint against the TTS service on :8001. server.py
# only reaches it per-request via tts_client.py, so this coming up first is
# fine -- it does not need TTS to be warm to start.
param(
  [string]$Root     = (Split-Path $PSScriptRoot -Parent),
  [string]$BindAddr = "0.0.0.0",
  [int]   $Port     = 8000
)

$py = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv python not found: $py" }

# This runs hidden, so the log is the only way to see anything. Kept out of
# the repo on purpose.
$logDir = Join-Path $env:LOCALAPPDATA "imood-voice"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$log = Join-Path $logDir "server.log"

Set-Location $Root
while ($true) {
  ("=== starting server.py {0} ===" -f (Get-Date -Format o)) |
    Out-File -FilePath $log -Append -Encoding utf8

  # Redirect through cmd rather than PowerShell: in Windows PowerShell 5.1 the
  # PowerShell append-redirect operator writes UTF-16LE, which interleaves with
  # the UTF-8 lines above and makes the log unreadable. cmd appends the child
  # process bytes verbatim, so the log stays plain UTF-8 the whole way down.
  & cmd.exe /c "`"$py`" -m uvicorn server:app --host $BindAddr --port $Port >> `"$log`" 2>&1"

  ("=== exited (code {0}), restarting in 5s ===" -f $LASTEXITCODE) |
    Out-File -FilePath $log -Append -Encoding utf8
  Start-Sleep -Seconds 5
}

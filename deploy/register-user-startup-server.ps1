# Registers the Windows imood-voice service (:8000) to start at logon,
# WITHOUT needing administrator. Sibling of
# register-user-startup-keepalive.ps1, which does the same for the WSL
# keepalive that holds the TTS service (:8001) up.
#
#   powershell -ExecutionPolicy Bypass -File C:\imood_project\imood-voice\deploy\register-user-startup-server.ps1
#
# Deliberately a separate shortcut from the keepalive rather than one combined
# entry, so the two can be turned off independently -- a dev box may want the
# TTS distro pinned without also running the Windows server.
#
# To disable: open shell:startup and delete imood-voice-server.lnk

$ErrorActionPreference = "Stop"

$runner = Join-Path $PSScriptRoot "run-imood-voice-server.ps1"
if (-not (Test-Path $runner)) { throw "runner script not found: $runner" }

$startup = [Environment]::GetFolderPath("Startup")
if (-not $startup) { throw "could not resolve the Startup folder" }
$lnk = Join-Path $startup "imood-voice-server.lnk"

$sh = New-Object -ComObject WScript.Shell
$s  = $sh.CreateShortcut($lnk)
$s.TargetPath       = (Get-Command powershell.exe).Source
$s.Arguments        = "-WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File `"$runner`""
$s.WorkingDirectory = Split-Path $PSScriptRoot -Parent
$s.WindowStyle      = 7
$s.Description      = "Run the imood-voice server (ASR + LLM + dialogue) on :8000"
$s.Save()

if (-not (Test-Path $lnk)) { throw "shortcut was not created: $lnk" }
Write-Host "registered: $lnk"
Write-Host "starting it now so you do not have to log out and back in..."
Start-Process -FilePath $s.TargetPath -ArgumentList $s.Arguments -WindowStyle Hidden
Write-Host ""
Write-Host "the LLM loads in ~2s but the ASR model can take longer on a cold"
Write-Host "HuggingFace cache. watch it with:"
Write-Host "    Get-Content `"$env:LOCALAPPDATA\imood-voice\server.log`" -Wait -Tail 20"
Write-Host "then check:  curl.exe -s http://127.0.0.1:8000/health"

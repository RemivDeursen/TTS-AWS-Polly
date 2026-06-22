## TTS AWS Polly

Small Windows TTS tools that synthesize speech with Amazon Polly and play it through a selected output device, usually VB-CABLE for Discord.

## Project Layout

```text
apps/
  local_tts.py
  discord_clipboard_tts.py
  discord_enter_tts.py

tts_core/
  audio.py
  config.py
  devices.py
  polly.py

packaging/
  TTS_Local.spec

scripts/
  build.ps1
```

`TTS_Local.py` remains as a compatibility launcher for the main local TTS app.

## Install

Install VB-CABLE, then set Discord's microphone to:

```text
CABLE Output (VB-Audio Virtual Cable)
```

Install Python packages:

```powershell
python -m pip install -r requirements.txt
```

Place `rootkey.csv` in the project root.

## Run

```powershell
python TTS_Local.py
python apps/discord_clipboard_tts.py
python apps/discord_enter_tts.py
```

The Discord Enter script needs Windows UI Automation access through `pywinauto`; if Discord does not expose its focused textbox text, use the clipboard script instead.

## Build

```powershell
.\scripts\build.ps1
```

Place `rootkey.csv` next to the built executable before running it.

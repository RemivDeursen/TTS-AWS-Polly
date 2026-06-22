## TTS AWS Polly

Small Windows TTS tools that synthesize speech with Amazon Polly and play it through a selected output device, usually VB-CABLE for Discord.

## Project Layout

```text
apps/
  local_tts.py

tts_core/
  audio.py
  config.py
  devices.py
  discord_monitor.py
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
.\scripts\run.ps1
```

The main app has a Discord toggle. When it is enabled, the app watches for Enter while Discord is active and tries to read the focused Discord textbox through Windows UI Automation.

Enable `Listen` to also play synthesized speech through your selected Windows audio device while the main output device, usually VB-CABLE, receives the same audio. Use settings to choose both the main output device and the listen device.

## Build

```powershell
.\scripts\build.ps1
```

Place `rootkey.csv` next to the built executable before running it.

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
  wowlink.py
  polly.py

RemTTS_Wowlink/
  RemTTS_Wowlink.toc
  RemTTS_Wowlink.lua

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

The app automatically uploads `cat_lexicon.pls` to Amazon Polly as `CatLexicon` in the configured region before first speech synthesis, then applies it to every Polly request.

## Run

```powershell
.\scripts\run.ps1
```

The main app has a Discord toggle. When it is enabled, the app watches for Enter while Discord is active and tries to read the focused Discord textbox through Windows UI Automation.

Enable `Listen` to also play synthesized speech through your selected Windows audio device while the main output device, usually VB-CABLE, receives the same audio. Use settings to choose both the main output device and the listen device.

Playback is fixed to 44100Hz output. Polly synthesis is requested as OGG/Vorbis and resampled to 44100Hz before playback.

## WoWLink

`WoWLink` reads your own typed WoW chat by watching keyboard input while World of Warcraft is the foreground window. It only captures while Scroll Lock is on, and it starts buffering a WoW message after you press Enter to open chat.

Turn on the `WoWLink` checkbox in the app, press Scroll Lock, then use WoW chat normally. Pressing Enter again sends the message and queues it for TTS. Escape cancels the current captured message.

Slash commands are ignored unless they are chat commands such as `/say`, `/party`, `/guild`, `/raid`, `/whisper`, `/yell`, `/emote`, or numbered channels like `/1`.

`RemTTS_Wowlink` is now optional. It can still be installed as an in-game status/helper addon, but live TTS no longer depends on `WoWChatLog.txt` because WoW only flushes that file when the game exits or reloads.

Install the optional addon by copying the `RemTTS_Wowlink` folder into your WoW addon folder, for example:

```text
World of Warcraft\_retail_\Interface\AddOns\RemTTS_Wowlink
```

## Build

```powershell
.\scripts\build.ps1
```

Place `rootkey.csv` next to the built executable before running it. `cat_lexicon.pls` is bundled into the executable build.

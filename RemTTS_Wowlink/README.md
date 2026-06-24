# RemTTS WoWLink

Small optional World of Warcraft helper addon for RemTTS.

RemTTS no longer depends on `WoWChatLog.txt` for live TTS because WoW only flushes that file when the game exits or reloads. The Python app captures your own typed WoW chat while World of Warcraft is focused and Scroll Lock is on.

## Install

Copy the `RemTTS_Wowlink` folder into:

```text
World of Warcraft\_retail_\Interface\AddOns\RemTTS_Wowlink
```

Restart WoW or run `/reload`, then enable `RemTTS WoWLink` in the addon list.

## Use

1. Toggle `WoWLink` in the RemTTS app.
2. Press Scroll Lock to enable capture.
3. Press Enter in WoW to open chat.
4. Type your message.
5. Press Enter again to send and speak it.

Use `/remtts` in game for addon status. The addon is not required for live capture.

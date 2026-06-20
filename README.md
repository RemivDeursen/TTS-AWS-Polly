## Step 1: Install VB-CABLE

Download and install:
[VB-CABLE Virtual Audio Device](https://vb-audio.com/Cable/)
After installing and rebooting, set Discord's microphone to:
```
CABLE Output (VB-Audio Virtual Cable)
```
Leave Discord's output device as your normal headset.
---

## Step 2: Install Python packages
```
pip install boto3 sounddevice soundfile pydub numpy scipy
```
You'll also want FFmpeg:
[FFmpeg Windows Builds](https://github.com/oop7/ffmpeg-install-guide/releases/tag/v2.6.0)

Verify:
```
ffmpeg -version
```

import io
from pathlib import Path
import csv
import boto3
from botocore.exceptions import ClientError
import numpy as np
import sounddevice as sd
import soundfile as sf

try:
    import soxr
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: install soxr with `python -m pip install soxr`."
    ) from exc

REGION = "eu-central-1"  # e.g., us-east-1, us-west-2
VB_CABLE_DEVICE_NAME = "CABLE Input (VB-Audio Virtual Cable)"
VB_CABLE_FALLBACK_DEVICE_INDEX = 39
POLLY_OGG_SAMPLE_RATES = (24000, 22050, 16000, 8000)
PLAYBACK_HEADROOM_DB = 1.0
PLAYBACK_HEADROOM = 10 ** (-PLAYBACK_HEADROOM_DB / 20)


def find_output_device_index(device_name, fallback_index):
    matches = []

    for index, device in enumerate(sd.query_devices()):
        if device["max_output_channels"] <= 0:
            continue
        if device_name.lower() in device["name"].lower():
            matches.append((index, device))

    if matches:
        for index, device in matches:
            hostapi = sd.query_hostapis(device["hostapi"])
            if "WASAPI" in hostapi["name"]:
                return index
        return matches[0][0]

    return fallback_index


def get_output_device_info(device_index):
    device = sd.query_devices(device_index, "output")
    return {
        "index": device_index,
        "name": device["name"],
        "sample_rate": int(device["default_samplerate"]),
        "max_channels": int(device["max_output_channels"]),
    }


def get_output_channels(device_info):
    candidates = [2, device_info["max_channels"], 1, 4, 8]
    candidates = list(dict.fromkeys(
        channels
        for channels in candidates
        if 0 < channels <= device_info["max_channels"]
    ))

    for channels in candidates:
        try:
            sd.check_output_settings(
                device=device_info["index"],
                samplerate=device_info["sample_rate"],
                channels=channels
            )
            return channels
        except sd.PortAudioError:
            pass

    raise RuntimeError(
        f"No valid channel count found for output device {device_info['index']} "
        f"({device_info['name']})."
    )


def synthesize_polly_ogg(text):
    last_error = None

    for sample_rate in POLLY_OGG_SAMPLE_RATES:
        try:
            response = polly.synthesize_speech(
                Text=text,
                VoiceId="Justin",
                OutputFormat="ogg_vorbis",
                SampleRate=str(sample_rate),
                Engine="neural"
            )
            ogg_bytes = response["AudioStream"].read()
            audio, decoded_sample_rate = sf.read(
                io.BytesIO(ogg_bytes),
                dtype="float32",
                always_2d=False
            )
            return audio, decoded_sample_rate
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code != "InvalidSampleRateException":
                raise
            last_error = exc

    raise RuntimeError(
        "Polly rejected all configured OGG sample rates: "
        f"{', '.join(str(rate) for rate in POLLY_OGG_SAMPLE_RATES)}."
    ) from last_error


def match_output_channels(audio, channels):
    audio = np.asarray(audio, dtype=np.float32)

    if audio.ndim == 1:
        return np.repeat(audio[:, np.newaxis], channels, axis=1)

    if audio.ndim != 2:
        raise ValueError(f"Expected mono or 2D audio, got shape {audio.shape}.")

    current_channels = audio.shape[1]
    if current_channels == channels:
        return audio
    if current_channels == 1:
        return np.repeat(audio, channels, axis=1)
    if current_channels > channels:
        return audio[:, :channels]

    padding = np.repeat(audio[:, -1:], channels - current_channels, axis=1)
    return np.concatenate((audio, padding), axis=1)


def prepare_for_playback(audio, channels):
    audio = match_output_channels(audio, channels)
    audio = np.asarray(audio, dtype=np.float32)
    audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)

    peak = np.max(np.abs(audio)) if audio.size else 0.0
    if peak > PLAYBACK_HEADROOM:
        audio *= PLAYBACK_HEADROOM / peak

    return np.ascontiguousarray(np.clip(audio, -1.0, 1.0), dtype=np.float32)


def load_aws_credentials():
    credentials_path = Path(__file__).with_name("rootkey.csv")

    with credentials_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        row = next(reader)

    return row["Access key ID"], row["Secret access key"]

aws_access_key_id, aws_secret_access_key = load_aws_credentials()
polly = boto3.client(
    "polly",
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=REGION
)

while True:
    text = input("Justin > ")

    if not text.strip():
        continue

    audio, polly_sample_rate = synthesize_polly_ogg(text)
    output_device_index = find_output_device_index(
        VB_CABLE_DEVICE_NAME,
        VB_CABLE_FALLBACK_DEVICE_INDEX
    )
    output_device = get_output_device_info(output_device_index)
    playback_sample_rate = output_device["sample_rate"]
    playback_channels = get_output_channels(output_device)

    if playback_sample_rate != polly_sample_rate:
        audio = soxr.resample(
            audio,
            polly_sample_rate,
            playback_sample_rate,
            quality="HQ"
        )

    audio = prepare_for_playback(audio, playback_channels)

    print("Output Device:", output_device["index"], output_device["name"])
    print("Polly Sample Rate:", polly_sample_rate)
    print("Playback Sample Rate:", playback_sample_rate)
    print("Playback Channels:", playback_channels)
    print("Peak:", np.max(np.abs(audio)) if audio.size else 0.0)
    print("Shape:", audio.shape)

    sd.play(
        audio,
        playback_sample_rate,
        device=output_device["index"]
    )

    sd.wait()

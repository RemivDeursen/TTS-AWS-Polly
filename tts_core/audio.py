import numpy as np
import sounddevice as sd

try:
    import soxr
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: install soxr with `python -m pip install soxr`."
    ) from exc

from .config import PLAYBACK_HEADROOM
from .devices import (
    AudioDeviceError,
    describe_portaudio_error,
    detect_output_format,
    get_output_device_info,
)
from .polly import synthesize_polly_ogg


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


def speak_text(text, output_device_index, engine, stop_event):
    audio, polly_sample_rate = synthesize_polly_ogg(text, engine)
    output_device = get_output_device_info(output_device_index)
    playback_sample_rate, playback_channels = detect_output_format(output_device)

    if playback_sample_rate != polly_sample_rate:
        audio = soxr.resample(
            audio,
            polly_sample_rate,
            playback_sample_rate,
            quality="HQ"
        )

    audio = prepare_for_playback(audio, playback_channels)

    if stop_event.is_set():
        return

    try:
        sd.play(
            audio,
            playback_sample_rate,
            device=output_device["index"]
        )
        sd.wait()
    except sd.PortAudioError as exc:
        try:
            sd.stop()
        except sd.PortAudioError:
            pass
        raise AudioDeviceError(
            f"Could not play audio through {output_device['name']}.\n\n"
            f"{describe_portaudio_error(exc)}"
        ) from exc

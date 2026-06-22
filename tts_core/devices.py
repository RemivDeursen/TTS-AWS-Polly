import sounddevice as sd

from .config import (
    COMMON_OUTPUT_SAMPLE_RATES,
    PREFERRED_CABLE_CHANNELS,
    PREFERRED_CABLE_SAMPLE_RATE,
    VB_CABLE_DEVICE_NAME,
    VB_CABLE_FALLBACK_DEVICE_INDEX,
)


class AudioDeviceError(RuntimeError):
    pass


def describe_portaudio_error(exc):
    message = str(exc)
    if "-9999" in message or "Unanticipated host error" in message:
        return (
            "Windows reported an audio host error while opening the output device. "
            "Try another output device, unplug/replug the audio device, restart apps "
            "using the device, or disable exclusive mode in Windows sound settings.\n\n"
            f"PortAudio details: {message}"
        )
    return message


def safe_query_devices():
    try:
        return sd.query_devices()
    except sd.PortAudioError as exc:
        raise AudioDeviceError(
            "Could not read Windows output devices.\n\n"
            f"{describe_portaudio_error(exc)}"
        ) from exc


def safe_query_hostapi(hostapi_index):
    try:
        return sd.query_hostapis(hostapi_index)["name"]
    except sd.PortAudioError:
        return "Unknown host API"


def hostapi_preference(hostapi_name):
    if "WASAPI" in hostapi_name:
        return 0
    if "DirectSound" in hostapi_name or "MME" in hostapi_name:
        return 1
    if "WDM-KS" in hostapi_name:
        return 2
    return 3


def can_open_output_format(device_index, sample_rate, channels):
    try:
        sd.check_output_settings(
            device=device_index,
            samplerate=sample_rate,
            channels=channels
        )
        return True
    except sd.PortAudioError:
        return False


def get_output_device_options():
    devices = []

    for index, device in enumerate(safe_query_devices()):
        if device["max_output_channels"] <= 0:
            continue

        devices.append({
            "index": index,
            "name": device["name"],
            "hostapi": safe_query_hostapi(device["hostapi"]),
            "max_channels": int(device["max_output_channels"]),
            "sample_rate": int(device["default_samplerate"]),
        })

    return devices


def format_output_device(device):
    return (
        f"{device['index']}: {device['name']} "
        f"({device['hostapi']}, {device['max_channels']}ch, "
        f"{device['sample_rate']}Hz)"
    )


def get_default_output_device_index():
    try:
        _default_input, default_output = sd.default.device
    except sd.PortAudioError:
        return None

    if default_output is None or default_output < 0:
        return None
    return int(default_output)


def choose_initial_output_device(devices):
    device_indexes = {device["index"] for device in devices}
    cable_index = choose_preferred_cable_output_device(devices)

    if cable_index in device_indexes:
        return cable_index

    default_index = get_default_output_device_index()
    if default_index in device_indexes:
        return default_index

    if VB_CABLE_FALLBACK_DEVICE_INDEX in device_indexes:
        return VB_CABLE_FALLBACK_DEVICE_INDEX

    return devices[0]["index"] if devices else None


def choose_initial_monitor_output_device(devices):
    device_indexes = {device["index"] for device in devices}
    default_index = get_default_output_device_index()

    if default_index in device_indexes:
        return default_index

    return devices[0]["index"] if devices else None


def get_output_device_info(device_index):
    try:
        device = sd.query_devices(device_index, "output")
    except sd.PortAudioError as exc:
        raise AudioDeviceError(
            f"Could not open output device {device_index}.\n\n"
            f"{describe_portaudio_error(exc)}"
        ) from exc

    return {
        "index": device_index,
        "name": device["name"],
        "sample_rate": int(device["default_samplerate"]),
        "max_channels": int(device["max_output_channels"]),
    }


def get_output_channel_candidates(max_channels):
    candidates = [2, max_channels, 1, 4, 8]
    return list(dict.fromkeys(
        channels
        for channels in candidates
        if 0 < channels <= max_channels
    ))


def get_output_sample_rate_candidates(default_sample_rate):
    candidates = [*COMMON_OUTPUT_SAMPLE_RATES, default_sample_rate]
    return list(dict.fromkeys(rate for rate in candidates if rate > 0))


def detect_output_format(device_info):
    sample_rates = get_output_sample_rate_candidates(device_info["sample_rate"])
    channels_by_preference = get_output_channel_candidates(device_info["max_channels"])
    errors = []

    for sample_rate in sample_rates:
        for channels in channels_by_preference:
            try:
                sd.check_output_settings(
                    device=device_info["index"],
                    samplerate=sample_rate,
                    channels=channels
                )
                return sample_rate, channels
            except sd.PortAudioError as exc:
                errors.append(
                    f"{sample_rate}Hz/{channels}ch: {describe_portaudio_error(exc)}"
                )

    detail = "\n".join(errors) if errors else "No sample rates or channel counts were available."
    raise AudioDeviceError(
        f"No valid output format found for device {device_info['index']} "
        f"({device_info['name']}).\n\n{detail}"
    )


def choose_preferred_cable_output_device(devices):
    matches = [
        device for device in devices
        if VB_CABLE_DEVICE_NAME.lower() in device["name"].lower()
    ]
    if not matches:
        return None

    matches.sort(key=lambda device: (
        hostapi_preference(device["hostapi"]),
        device["index"]
    ))

    for device in matches:
        if can_open_output_format(
            device["index"],
            PREFERRED_CABLE_SAMPLE_RATE,
            PREFERRED_CABLE_CHANNELS
        ):
            return device["index"]

    for device in matches:
        try:
            detect_output_format({
                "index": device["index"],
                "name": device["name"],
                "sample_rate": device["sample_rate"],
                "max_channels": device["max_channels"],
            })
            return device["index"]
        except AudioDeviceError:
            continue

    return None

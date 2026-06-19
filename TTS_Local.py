import io
from pathlib import Path
import csv
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

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
POLLY_OGG_SAMPLE_RATES_BY_ENGINE = {
    "neural": (24000, 22050, 16000, 8000),
    "standard": (22050, 24000, 16000, 8000),
}
POLLY_ENGINE_OPTIONS = tuple(POLLY_OGG_SAMPLE_RATES_BY_ENGINE)
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


def get_output_device_options():
    devices = []

    for index, device in enumerate(sd.query_devices()):
        if device["max_output_channels"] <= 0:
            continue

        hostapi = sd.query_hostapis(device["hostapi"])
        devices.append({
            "index": index,
            "name": device["name"],
            "hostapi": hostapi["name"],
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
    default_input, default_output = sd.default.device
    if default_output is None or default_output < 0:
        return None
    return int(default_output)


def choose_initial_output_device(devices):
    device_indexes = {device["index"] for device in devices}
    cable_index = find_output_device_index(VB_CABLE_DEVICE_NAME, -1)

    if cable_index in device_indexes:
        return cable_index

    default_index = get_default_output_device_index()
    if default_index in device_indexes:
        return default_index

    if VB_CABLE_FALLBACK_DEVICE_INDEX in device_indexes:
        return VB_CABLE_FALLBACK_DEVICE_INDEX

    return devices[0]["index"] if devices else None


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


def synthesize_polly_ogg(text, engine):
    last_error = None
    sample_rates = POLLY_OGG_SAMPLE_RATES_BY_ENGINE[engine]

    for sample_rate in sample_rates:
        try:
            response = polly.synthesize_speech(
                Text=text,
                VoiceId="Justin",
                OutputFormat="ogg_vorbis",
                SampleRate=str(sample_rate),
                Engine=engine
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
        f"Polly rejected all configured OGG sample rates for {engine}: "
        f"{', '.join(str(rate) for rate in sample_rates)}."
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


def speak_text(text, output_device_index, engine, stop_event):
    audio, polly_sample_rate = synthesize_polly_ogg(text, engine)
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

    if stop_event.is_set():
        return

    print("Output Device:", output_device["index"], output_device["name"])
    print("Polly Engine:", engine)
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


class TTSApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Local TTS")
        self.geometry("560x260")
        self.minsize(440, 220)
        self.speaking = False
        self.output_devices = []
        self.stop_event = threading.Event()
        self.message_queue = queue.Queue()
        self.worker_running = False
        self.worker_lock = threading.Lock()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        device_label = ttk.Label(frame, text="Output device")
        device_label.grid(row=0, column=0, sticky="w")

        self.device_choice = tk.StringVar()
        self.device_combo = ttk.Combobox(
            frame,
            textvariable=self.device_choice,
            state="readonly"
        )
        self.device_combo.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0))

        engine_label = ttk.Label(frame, text="Engine")
        engine_label.grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.engine_choice = tk.StringVar(value="neural")
        self.engine_combo = ttk.Combobox(
            frame,
            textvariable=self.engine_choice,
            values=POLLY_ENGINE_OPTIONS,
            state="readonly"
        )
        self.engine_combo.grid(
            row=1,
            column=1,
            columnspan=3,
            sticky="ew",
            padx=(8, 0),
            pady=(8, 0)
        )

        self.textbox = tk.Text(frame, height=5, wrap="word", undo=True)
        self.textbox.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(10, 0))
        self.textbox.focus_set()

        self.status = tk.StringVar(value="Ready")
        status_label = ttk.Label(frame, textvariable=self.status)
        status_label.grid(row=3, column=0, sticky="w", pady=(10, 0))

        self.clear_button = ttk.Button(frame, text="Clear", command=self.clear_text)
        self.clear_button.grid(row=3, column=1, sticky="e", padx=(8, 0), pady=(10, 0))

        self.stop_button = ttk.Button(frame, text="Stop", command=self.stop_speaking)
        self.stop_button.grid(row=3, column=2, sticky="e", padx=(8, 0), pady=(10, 0))
        self.stop_button.configure(state="disabled")

        self.speak_button = ttk.Button(frame, text="Speak", command=self.send_current_text)
        self.speak_button.grid(row=3, column=3, sticky="e", padx=(8, 0), pady=(10, 0))

        self.textbox.bind("<Return>", self.speak_from_enter)
        self.textbox.bind("<Shift-Return>", self.insert_newline)
        self.bind("<Escape>", self.stop_from_escape)
        self.refresh_output_devices()

    def get_text(self):
        return self.textbox.get("1.0", "end").strip()

    def refresh_output_devices(self):
        self.output_devices = get_output_device_options()
        labels = [format_output_device(device) for device in self.output_devices]
        self.device_combo.configure(values=labels)

        initial_index = choose_initial_output_device(self.output_devices)
        if initial_index is None:
            self.device_choice.set("")
            self.status.set("No output devices found")
            self.speak_button.configure(state="disabled")
            return

        for label, device in zip(labels, self.output_devices):
            if device["index"] == initial_index:
                self.device_choice.set(label)
                self.status.set("Ready")
                self.speak_button.configure(state="normal")
                return

    def get_selected_output_device_index(self):
        selected = self.device_choice.get()

        for device in self.output_devices:
            if format_output_device(device) == selected:
                return device["index"]

        raise RuntimeError("Choose an output device first.")

    def get_selected_engine(self):
        engine = self.engine_choice.get()
        if engine not in POLLY_OGG_SAMPLE_RATES_BY_ENGINE:
            raise RuntimeError("Choose a Polly engine first.")
        return engine

    def clear_text(self):
        self.textbox.delete("1.0", "end")
        self.status.set("Ready")
        self.textbox.focus_set()

    def set_speaking(self, speaking):
        self.speaking = speaking
        self.speak_button.configure(state="normal")
        self.clear_button.configure(state="normal")
        self.stop_button.configure(state="normal" if speaking else "disabled")
        self.device_combo.configure(state="disabled" if speaking else "readonly")
        self.engine_combo.configure(state="disabled" if speaking else "readonly")
        self.status.set("Speaking..." if speaking else "Ready")

    def speak_from_enter(self, _event):
        self.send_current_text()
        return "break"

    def send_current_text(self):
        text = self.get_text()
        if not text:
            self.status.set("Type something first")
            return False

        if self.enqueue_speech(text):
            self.textbox.delete("1.0", "end")
            self.textbox.focus_set()
            return True

        return False

    def stop_from_escape(self, _event):
        self.stop_speaking()
        return "break"

    def insert_newline(self, _event):
        self.textbox.insert("insert", "\n")
        return "break"

    def enqueue_speech(self, text):
        try:
            output_device_index = self.get_selected_output_device_index()
            engine = self.get_selected_engine()
        except RuntimeError as exc:
            self.show_error(exc)
            return False

        self.message_queue.put((text, output_device_index, engine))
        queued_count = self.message_queue.qsize()

        with self.worker_lock:
            if self.worker_running:
                self.status.set(f"Queued {queued_count}")
                return True

            self.worker_running = True
            self.stop_event = threading.Event()

        self.set_speaking(True)
        threading.Thread(target=self.play_queue, daemon=True).start()
        return True

    def stop_speaking(self):
        if not self.worker_running:
            return

        self.stop_event.set()
        self.clear_queue()
        sd.stop()
        self.status.set("Stopping...")

    def clear_queue(self):
        while True:
            try:
                self.message_queue.get_nowait()
                self.message_queue.task_done()
            except queue.Empty:
                return

    def play_queue(self):
        stop_event = self.stop_event

        try:
            while not stop_event.is_set():
                try:
                    text, output_device_index, engine = self.message_queue.get_nowait()
                except queue.Empty:
                    break

                queued_after_this = self.message_queue.qsize()
                self.after(0, self.update_playback_status, queued_after_this)
                speak_text(text, output_device_index, engine, stop_event)
                self.message_queue.task_done()
        except Exception as exc:
            stop_event.set()
            self.clear_queue()
            self.after(0, self.show_error, exc)
        finally:
            restart_worker = False

            with self.worker_lock:
                self.worker_running = False
                if not stop_event.is_set() and not self.message_queue.empty():
                    self.worker_running = True
                    self.stop_event = threading.Event()
                    restart_worker = True

            if restart_worker:
                threading.Thread(target=self.play_queue, daemon=True).start()
            else:
                self.after(0, self.set_speaking, False)

    def update_playback_status(self, queued_count):
        if queued_count:
            self.status.set(f"Speaking... {queued_count} queued")
        else:
            self.status.set("Speaking...")

    def show_error(self, exc):
        self.status.set("Error")
        messagebox.showerror("TTS error", str(exc))


if __name__ == "__main__":
    TTSApp().mainloop()

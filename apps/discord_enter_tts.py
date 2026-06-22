import ctypes
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import sounddevice as sd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tts_core.audio import speak_text
from tts_core.config import POLLY_ENGINE_OPTIONS, POLLY_OGG_SAMPLE_RATES_BY_ENGINE
from tts_core.devices import (
    AudioDeviceError,
    choose_initial_output_device,
    format_output_device,
    get_output_device_options,
)


POLL_INTERVAL_MS = 25
VK_RETURN = 0x0D


def get_foreground_window_title():
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""

    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def discord_is_foreground():
    return "discord" in get_foreground_window_title().lower()


def return_key_is_down():
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_RETURN) & 0x8000)


def get_focused_uia_text():
    try:
        from pywinauto.controls.uiawrapper import UIAWrapper
        from pywinauto.uia_defines import IUIA
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: install pywinauto with "
            "`python -m pip install pywinauto`."
        ) from exc

    element_info = IUIA().get_focused_element()
    wrapper = UIAWrapper(element_info)
    candidates = []

    try:
        value = wrapper.iface_value.CurrentValue
        if value:
            candidates.append(value)
    except Exception:
        pass

    try:
        legacy_value = wrapper.legacy_properties().get("Value")
        if legacy_value:
            candidates.append(legacy_value)
    except Exception:
        pass

    try:
        text = wrapper.window_text()
        if text:
            candidates.append(text)
    except Exception:
        pass

    cleaned = [
        candidate.strip()
        for candidate in candidates
        if candidate and candidate.strip()
    ]
    cleaned = [
        candidate
        for candidate in cleaned
        if not candidate.lower().startswith(("message #", "message @"))
    ]

    return max(cleaned, key=len) if cleaned else ""


class DiscordEnterTTSApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Discord Enter TTS")
        self.geometry("640x260")
        self.minsize(520, 240)

        self.output_devices = []
        self.message_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_running = False
        self.worker_lock = threading.Lock()
        self.monitoring = tk.BooleanVar(value=False)
        self.device_choice = tk.StringVar()
        self.engine_choice = tk.StringVar(value="neural")
        self.return_was_down = False
        self.last_spoken_text = ""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        device_label = ttk.Label(frame, text="Output device")
        device_label.grid(row=0, column=0, sticky="w")

        self.device_combo = ttk.Combobox(
            frame,
            textvariable=self.device_choice,
            state="readonly",
            width=64
        )
        self.device_combo.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0))

        engine_label = ttk.Label(frame, text="Engine")
        engine_label.grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.engine_combo = ttk.Combobox(
            frame,
            textvariable=self.engine_choice,
            values=POLLY_ENGINE_OPTIONS,
            state="readonly",
            width=20
        )
        self.engine_combo.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        self.preview = tk.Text(frame, height=4, wrap="word", state="disabled")
        self.preview.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(12, 0))
        frame.rowconfigure(2, weight=1)

        self.status = tk.StringVar(value="Ready")
        status_label = ttk.Label(frame, textvariable=self.status)
        status_label.grid(row=3, column=0, sticky="w", pady=(10, 0))

        refresh_button = ttk.Button(frame, text="Refresh", command=self.refresh_output_devices)
        refresh_button.grid(row=3, column=1, sticky="e", padx=(8, 0), pady=(10, 0))

        self.monitor_button = ttk.Button(
            frame,
            text="Start",
            command=self.toggle_monitoring
        )
        self.monitor_button.grid(row=3, column=2, sticky="e", padx=(8, 0), pady=(10, 0))

        self.stop_button = ttk.Button(frame, text="Stop Audio", command=self.stop_speaking)
        self.stop_button.grid(row=3, column=3, sticky="e", padx=(8, 0), pady=(10, 0))
        self.stop_button.configure(state="disabled")

        self.refresh_output_devices()
        self.after(POLL_INTERVAL_MS, self.poll_enter_key)

    def refresh_output_devices(self):
        try:
            self.output_devices = get_output_device_options()
        except AudioDeviceError as exc:
            self.output_devices = []
            self.device_combo.configure(values=[])
            self.device_choice.set("")
            self.status.set("Audio device error")
            self.show_error(exc)
            return

        labels = [format_output_device(device) for device in self.output_devices]
        self.device_combo.configure(values=labels)

        if self.device_choice.get() in labels:
            return

        initial_index = choose_initial_output_device(self.output_devices)
        for label, device in zip(labels, self.output_devices):
            if device["index"] == initial_index:
                self.device_choice.set(label)
                self.status.set("Ready")
                return

        self.status.set("No output devices found")

    def toggle_monitoring(self):
        if self.monitoring.get():
            self.monitoring.set(False)
            self.monitor_button.configure(text="Start")
            self.status.set("Paused")
            return

        try:
            self.get_selected_output_device_index()
            self.get_selected_engine()
            get_focused_uia_text()
        except RuntimeError as exc:
            self.show_error(exc)
            return

        self.return_was_down = return_key_is_down()
        self.monitoring.set(True)
        self.monitor_button.configure(text="Pause")
        self.status.set("Watching Discord Enter")

    def poll_enter_key(self):
        try:
            is_down = return_key_is_down()
            pressed_now = is_down and not self.return_was_down
            self.return_was_down = is_down

            if self.monitoring.get() and pressed_now and discord_is_foreground():
                self.handle_discord_enter()
        finally:
            self.after(POLL_INTERVAL_MS, self.poll_enter_key)

    def handle_discord_enter(self):
        try:
            text = get_focused_uia_text()
        except RuntimeError as exc:
            self.monitoring.set(False)
            self.monitor_button.configure(text="Start")
            self.show_error(exc)
            return

        if not text:
            self.status.set("Enter seen; focused text was not exposed")
            return

        if text == self.last_spoken_text:
            return

        self.last_spoken_text = text
        self.enqueue_speech(text)

    def enqueue_speech(self, text):
        try:
            output_device_index = self.get_selected_output_device_index()
            engine = self.get_selected_engine()
        except RuntimeError as exc:
            self.show_error(exc)
            return

        self.set_preview(text)
        self.message_queue.put((text, output_device_index, engine))
        queued_count = self.message_queue.qsize()

        with self.worker_lock:
            if self.worker_running:
                self.status.set(f"Queued {queued_count}")
                return

            self.worker_running = True
            self.stop_event = threading.Event()

        self.set_speaking(True)
        threading.Thread(target=self.play_queue, daemon=True).start()

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

    def set_preview(self, text):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def set_speaking(self, speaking):
        self.stop_button.configure(state="normal" if speaking else "disabled")
        if speaking:
            self.status.set("Speaking...")
        elif self.monitoring.get():
            self.status.set("Watching Discord Enter")
        else:
            self.status.set("Ready")

    def stop_speaking(self):
        if not self.worker_running:
            return

        self.stop_event.set()
        self.clear_queue()
        try:
            sd.stop()
        except sd.PortAudioError:
            pass
        self.status.set("Stopping...")

    def clear_queue(self):
        while True:
            try:
                self.message_queue.get_nowait()
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
        messagebox.showerror("Discord Enter TTS", str(exc))


if __name__ == "__main__":
    DiscordEnterTTSApp().mainloop()

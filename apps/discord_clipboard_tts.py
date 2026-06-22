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


POLL_INTERVAL_MS = 500


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


class DiscordClipboardTTSApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Discord Clipboard TTS")
        self.geometry("640x260")
        self.minsize(520, 240)

        self.output_devices = []
        self.message_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_running = False
        self.worker_lock = threading.Lock()
        self.monitoring = tk.BooleanVar(value=False)
        self.discord_only = tk.BooleanVar(value=True)
        self.device_choice = tk.StringVar()
        self.engine_choice = tk.StringVar(value="neural")
        self.last_clipboard_text = ""

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

        discord_only_check = ttk.Checkbutton(
            frame,
            text="Only while Discord is active",
            variable=self.discord_only
        )
        discord_only_check.grid(row=1, column=2, columnspan=2, sticky="e", pady=(8, 0))

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
        self.after(POLL_INTERVAL_MS, self.poll_clipboard)

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
        except RuntimeError as exc:
            self.show_error(exc)
            return

        self.prime_clipboard()
        self.monitoring.set(True)
        self.monitor_button.configure(text="Pause")
        self.status.set("Watching clipboard")

    def prime_clipboard(self):
        self.last_clipboard_text = self.read_clipboard_text()

    def poll_clipboard(self):
        try:
            if self.monitoring.get() and self.should_accept_clipboard():
                text = self.read_clipboard_text()
                if text and text != self.last_clipboard_text:
                    self.last_clipboard_text = text
                    self.enqueue_speech(text)
        finally:
            self.after(POLL_INTERVAL_MS, self.poll_clipboard)

    def should_accept_clipboard(self):
        return not self.discord_only.get() or discord_is_foreground()

    def read_clipboard_text(self):
        try:
            return self.clipboard_get().strip()
        except tk.TclError:
            return ""

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
        self.status.set("Speaking..." if speaking else "Watching clipboard")

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
        messagebox.showerror("Discord Clipboard TTS", str(exc))


if __name__ == "__main__":
    DiscordClipboardTTSApp().mainloop()

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
from tts_core.discord_monitor import (
    POLL_INTERVAL_MS,
    discord_is_foreground,
    get_focused_uia_text,
    return_key_is_down,
)
from tts_core.devices import (
    AudioDeviceError,
    choose_initial_monitor_output_device,
    choose_initial_output_device,
    format_output_device,
    get_output_device_options,
)


class TTSApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Local TTS")
        self.geometry("560x220")
        self.minsize(440, 200)
        self.output_devices = []
        self.settings_window = None
        self.stop_event = threading.Event()
        self.message_queue = queue.Queue()
        self.worker_running = False
        self.worker_lock = threading.Lock()
        self.device_choice = tk.StringVar()
        self.monitor_device_choice = tk.StringVar()
        self.engine_choice = tk.StringVar(value="neural")
        self.discord_enabled = tk.BooleanVar(value=False)
        self.monitor_enabled = tk.BooleanVar(value=False)
        self.return_was_down = False
        self.last_discord_text = ""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.textbox = tk.Text(frame, height=5, wrap="word", undo=True)
        self.textbox.grid(row=0, column=0, columnspan=7, sticky="nsew")
        self.textbox.focus_set()

        self.status = tk.StringVar(value="Ready")
        status_label = ttk.Label(frame, textvariable=self.status)
        status_label.grid(row=1, column=0, sticky="w", pady=(10, 0))

        self.discord_check = ttk.Checkbutton(
            frame,
            text="Discord",
            variable=self.discord_enabled,
            command=self.toggle_discord_monitoring
        )
        self.discord_check.grid(row=1, column=1, sticky="e", padx=(8, 0), pady=(10, 0))

        self.monitor_check = ttk.Checkbutton(
            frame,
            text="Listen",
            variable=self.monitor_enabled
        )
        self.monitor_check.grid(row=1, column=2, sticky="e", padx=(8, 0), pady=(10, 0))

        self.settings_button = ttk.Button(
            frame,
            text="\u2699",
            width=3,
            command=self.open_settings
        )
        self.settings_button.grid(row=1, column=3, sticky="e", padx=(8, 0), pady=(10, 0))

        self.clear_button = ttk.Button(frame, text="Clear", command=self.clear_text)
        self.clear_button.grid(row=1, column=4, sticky="e", padx=(8, 0), pady=(10, 0))

        self.stop_button = ttk.Button(frame, text="Stop", command=self.stop_speaking)
        self.stop_button.grid(row=1, column=5, sticky="e", padx=(8, 0), pady=(10, 0))
        self.stop_button.configure(state="disabled")

        self.speak_button = ttk.Button(frame, text="Speak", command=self.send_current_text)
        self.speak_button.grid(row=1, column=6, sticky="e", padx=(8, 0), pady=(10, 0))

        self.textbox.bind("<Return>", self.speak_from_enter)
        self.textbox.bind("<Shift-Return>", self.insert_newline)
        self.bind("<Escape>", self.stop_from_escape)
        self.refresh_output_devices()
        self.after(POLL_INTERVAL_MS, self.poll_discord_enter)
        self.after(100, self.open_settings)

    def get_text(self):
        return self.textbox.get("1.0", "end").strip()

    def refresh_output_devices(self):
        try:
            self.output_devices = get_output_device_options()
        except AudioDeviceError as exc:
            self.output_devices = []
            self.device_choice.set("")
            self.monitor_device_choice.set("")
            self.status.set("Audio device error")
            self.speak_button.configure(state="disabled")
            self.after(0, self.show_error, exc)
            return

        labels = [format_output_device(device) for device in self.output_devices]

        initial_index = choose_initial_output_device(self.output_devices)
        monitor_initial_index = choose_initial_monitor_output_device(self.output_devices)
        if initial_index is None:
            self.device_choice.set("")
            self.monitor_device_choice.set("")
            self.status.set("No output devices found")
            self.speak_button.configure(state="disabled")
            return

        for label, device in zip(labels, self.output_devices):
            if device["index"] == initial_index:
                self.device_choice.set(label)
            if device["index"] == monitor_initial_index:
                self.monitor_device_choice.set(label)

        self.set_ready_status()
        self.speak_button.configure(state="normal")

    def open_settings(self):
        if self.worker_running:
            return

        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        settings = tk.Toplevel(self)
        self.settings_window = settings
        settings.title("Settings")
        settings.transient(self)
        settings.resizable(False, False)

        frame = ttk.Frame(settings, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        device_label = ttk.Label(frame, text="Output device")
        device_label.grid(row=0, column=0, sticky="w")

        labels = [format_output_device(device) for device in self.output_devices]
        device_combo = ttk.Combobox(
            frame,
            textvariable=self.device_choice,
            values=labels,
            state="readonly",
            width=70
        )
        device_combo.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0))

        monitor_check = ttk.Checkbutton(
            frame,
            text="Play through Windows device",
            variable=self.monitor_enabled,
            command=lambda: self.update_monitor_device_state(monitor_combo)
        )
        monitor_check.grid(row=1, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 0))

        monitor_label = ttk.Label(frame, text="Listen device")
        monitor_label.grid(row=2, column=0, sticky="w", pady=(8, 0))

        monitor_combo = ttk.Combobox(
            frame,
            textvariable=self.monitor_device_choice,
            values=labels,
            state="readonly" if self.monitor_enabled.get() else "disabled",
            width=70
        )
        monitor_combo.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(8, 0))

        engine_label = ttk.Label(frame, text="Engine")
        engine_label.grid(row=3, column=0, sticky="w", pady=(8, 0))

        engine_combo = ttk.Combobox(
            frame,
            textvariable=self.engine_choice,
            values=POLLY_ENGINE_OPTIONS,
            state="readonly",
            width=20
        )
        engine_combo.grid(row=3, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 0))

        refresh_button = ttk.Button(
            frame,
            text="Refresh",
            command=lambda: self.refresh_settings_devices(device_combo, monitor_combo)
        )
        refresh_button.grid(row=4, column=1, sticky="e", pady=(12, 0))

        done_button = ttk.Button(frame, text="Done", command=settings.destroy)
        done_button.grid(row=4, column=2, sticky="e", padx=(8, 0), pady=(12, 0))

        settings.protocol("WM_DELETE_WINDOW", settings.destroy)
        settings.grab_set()
        self.center_child_window(settings)
        settings.focus_set()

    def center_child_window(self, child):
        self.update_idletasks()
        child.update_idletasks()

        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_width = self.winfo_width()
        parent_height = self.winfo_height()
        child_width = child.winfo_reqwidth()
        child_height = child.winfo_reqheight()

        x = parent_x + max((parent_width - child_width) // 2, 0)
        y = parent_y + max((parent_height - child_height) // 2, 0)
        child.geometry(f"+{x}+{y}")

    def refresh_settings_devices(self, device_combo, monitor_combo):
        self.refresh_output_devices()
        labels = [format_output_device(device) for device in self.output_devices]
        device_combo.configure(values=labels)
        monitor_combo.configure(values=labels)
        self.update_monitor_device_state(monitor_combo)

    def update_monitor_device_state(self, monitor_combo):
        monitor_combo.configure(
            state="readonly" if self.monitor_enabled.get() else "disabled"
        )

    def get_selected_output_device_index(self):
        selected = self.device_choice.get()

        for device in self.output_devices:
            if format_output_device(device) == selected:
                return device["index"]

        raise RuntimeError("Choose an output device first.")

    def get_selected_monitor_device_index(self):
        if not self.monitor_enabled.get():
            return None

        selected = self.monitor_device_choice.get()

        for device in self.output_devices:
            if format_output_device(device) == selected:
                return device["index"]

        raise RuntimeError("Choose a listen device first.")

    def get_selected_engine(self):
        engine = self.engine_choice.get()
        if engine not in POLLY_OGG_SAMPLE_RATES_BY_ENGINE:
            raise RuntimeError("Choose a Polly engine first.")
        return engine

    def clear_text(self):
        self.textbox.delete("1.0", "end")
        self.set_ready_status()
        self.textbox.focus_set()

    def set_ready_status(self):
        self.status.set("Ready (Discord on)" if self.discord_enabled.get() else "Ready")

    def set_speaking(self, speaking):
        self.speak_button.configure(state="normal")
        self.clear_button.configure(state="normal")
        self.stop_button.configure(state="normal" if speaking else "disabled")
        self.settings_button.configure(state="disabled" if speaking else "normal")
        if speaking:
            self.status.set("Speaking...")
        else:
            self.set_ready_status()

    def toggle_discord_monitoring(self):
        if not self.discord_enabled.get():
            self.set_ready_status()
            return

        try:
            self.get_selected_output_device_index()
            self.get_selected_engine()
            get_focused_uia_text()
        except RuntimeError as exc:
            self.discord_enabled.set(False)
            self.show_error(exc)
            return

        self.return_was_down = return_key_is_down()
        self.last_discord_text = ""
        self.set_ready_status()

    def poll_discord_enter(self):
        try:
            is_down = return_key_is_down()
            pressed_now = is_down and not self.return_was_down
            self.return_was_down = is_down

            if self.discord_enabled.get() and pressed_now and discord_is_foreground():
                self.speak_focused_discord_text()
        finally:
            self.after(POLL_INTERVAL_MS, self.poll_discord_enter)

    def speak_focused_discord_text(self):
        try:
            text = get_focused_uia_text()
        except RuntimeError as exc:
            self.discord_enabled.set(False)
            self.show_error(exc)
            return

        if not text:
            self.status.set("Discord Enter seen; textbox text was not exposed")
            return

        if text == self.last_discord_text:
            return

        self.last_discord_text = text
        self.enqueue_speech(text)


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
            monitor_device_index = self.get_selected_monitor_device_index()
            engine = self.get_selected_engine()
        except RuntimeError as exc:
            self.show_error(exc)
            return False

        self.message_queue.put((text, output_device_index, monitor_device_index, engine))
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
                    text, output_device_index, monitor_device_index, engine = self.message_queue.get_nowait()
                except queue.Empty:
                    break

                queued_after_this = self.message_queue.qsize()
                self.after(0, self.update_playback_status, queued_after_this)
                speak_text(text, output_device_index, engine, stop_event, monitor_device_index)
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

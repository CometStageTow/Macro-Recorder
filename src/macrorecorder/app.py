import json
import queue
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass
from tkinter import filedialog, messagebox
from typing import Any, Dict, List, Optional

from pynput import keyboard, mouse
from pynput.keyboard import Controller as KeyController
from pynput.keyboard import GlobalHotKeys, Key
from pynput.mouse import Button
from pynput.mouse import Controller as MouseController


# ----------------------------
# Data models
# ----------------------------
@dataclass
class Event:
    t: float
    type: str
    data: Dict[str, Any]


@dataclass
class Recording:
    events: List[Event]
    started_at: float


# ----------------------------
# Macro App
# ----------------------------
class MacroApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Macro Recorder")
        self.root.geometry("720x520")

        # State
        self.recording: bool = False
        self.in_playback: bool = False
        self.abort_flag: bool = False
        self.rec: Optional[Recording] = None
        self.last_t: float = 0.0

        # Controllers for playback
        self.key_ctrl = KeyController()
        self.mouse_ctrl = MouseController()

        # UI state
        self.status_var = tk.StringVar(value="Idle – Ready")
        self.loop_count = tk.IntVar(value=1)
        self.loop_infinite = tk.BooleanVar(value=False)

        # Thread-safe log queue
        self._log_q: "queue.Queue[str]" = queue.Queue()

        self._build_ui()

        # Input listeners (always on)
        self.kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self.ms_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll,
        )
        self.kb_listener.start()
        self.ms_listener.start()

        # Global hotkeys
        self.hotkeys = GlobalHotKeys(
            {
                "<ctrl>+<shift>+r": self.toggle_record,
                "<ctrl>+<shift>+p": self.play,
                "<ctrl>+<shift>+x": self.abort,
            }
        )
        self.hotkeys.start()

        # Pump log to UI
        self._pump_log()

    # ----------------------------
    # UI
    # ----------------------------
    def _build_ui(self) -> None:
        pad = 8

        tk.Label(
            self.root,
            text="Macro Recorder",
            font=("Segoe UI", 16, "bold"),
        ).pack(pady=(12, 6))

        tk.Label(
            self.root,
            text=("Hotkeys: Record (Ctrl+Shift+R), Play (Ctrl+Shift+P), Abort (Ctrl+Shift+X)"),
        ).pack()

        self.status_lbl = tk.Label(self.root, textvariable=self.status_var, fg="#2b6cb0")
        self.status_lbl.pack(pady=(6, 10))

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=pad)

        self.btn_record = tk.Button(
            btn_frame,
            text="● Record",
            width=12,
            command=self.toggle_record,
            fg="red",
        )
        self.btn_record.grid(row=0, column=0, padx=pad)

        self.btn_play = tk.Button(
            btn_frame,
            text="► Play",
            width=12,
            command=self.play,
        )
        self.btn_play.grid(row=0, column=1, padx=pad)

        self.btn_abort = tk.Button(
            btn_frame,
            text="⨂ Abort",
            width=12,
            command=self.abort,
        )
        self.btn_abort.grid(row=0, column=2, padx=pad)

        self.btn_save = tk.Button(
            btn_frame,
            text="💾 Save",
            width=12,
            command=self.save,
        )
        self.btn_save.grid(row=1, column=0, padx=pad, pady=(pad, 0))

        self.btn_load = tk.Button(
            btn_frame,
            text="📂 Load",
            width=12,
            command=self.load,
        )
        self.btn_load.grid(row=1, column=1, padx=pad, pady=(pad, 0))

        loop_frame = tk.Frame(self.root)
        loop_frame.pack(pady=(pad, 0))
        tk.Label(loop_frame, text="Loop count:").pack(side=tk.LEFT)
        tk.Entry(loop_frame, textvariable=self.loop_count, width=6).pack(
            side=tk.LEFT,
            padx=(6, 0),
        )
        tk.Checkbutton(
            loop_frame,
            text="Infinite",
            variable=self.loop_infinite,
        ).pack(side=tk.LEFT, padx=(12, 0))

        # Log window
        log_frame = tk.Frame(self.root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(pad, pad))

        self.log = tk.Text(log_frame, height=16, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = tk.Scrollbar(log_frame, command=self.log.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb.set)

    def _set_status(self, s: str) -> None:
        self.status_var.set(s)

    def _post(self, s: str) -> None:
        self._log_q.put(s)

    def _pump_log(self) -> None:
        try:
            while True:
                line = self._log_q.get_nowait()
                self.log.insert(tk.END, line + "\n")
                self.log.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._pump_log)

    # ----------------------------
    # Recording
    # ----------------------------
    def toggle_record(self) -> None:
        if self.in_playback:
            self._post("Cannot record during playback.")
            return

        if not self.recording:
            self.recording = True
            self.abort_flag = False
            self.rec = Recording(events=[], started_at=time.perf_counter())
            self.last_t = 0.0
            self._set_status("Recording… (Ctrl+Shift+R to stop)")
            self._post("Recording started.")
            self.btn_record.configure(text="■ Stop")
        else:
            self.recording = False
            n = len(self.rec.events) if self.rec else 0
            self._set_status(f"Recorded {n} events. Ready.")
            self._post(f"Recording stopped. Captured {n} events.")
            self.btn_record.configure(text="● Record")

    def _record(self, etype: str, **data: Any) -> None:
        if not self.recording or self.in_playback or self.rec is None:
            return
        t = time.perf_counter() - self.rec.started_at
        self.rec.events.append(Event(t=t, type=etype, data=data))

    # Keyboard events
    def _on_key_press(self, key) -> None:
        self._record("key_press", key=self._key_to_str(key))

    def _on_key_release(self, key) -> None:
        self._record("key_release", key=self._key_to_str(key))

    # Mouse events
    def _on_mouse_move(self, x: int, y: int) -> None:
        # Reduce noise: only log moves while recording every ~15ms
        if not self.recording or self.rec is None or self.in_playback:
            return
        now = time.perf_counter() - self.rec.started_at
        if now - self.last_t >= 0.015:
            self.last_t = now
            self.rec.events.append(Event(t=now, type="mouse_move", data={"x": x, "y": y}))

    def _on_mouse_click(self, x: int, y: int, button: Button, pressed: bool) -> None:
        self._record(
            "mouse_click",
            x=x,
            y=y,
            button=str(button).split(".")[-1],
            pressed=pressed,
        )

    def _on_mouse_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._record("mouse_scroll", x=x, y=y, dx=dx, dy=dy)

    @staticmethod
    def _key_to_str(key) -> str:
        try:
            if isinstance(key, Key):
                return f"Key.{key.name}"
            return str(key).strip("'")
        except Exception:
            return str(key)

    # ----------------------------
    # Playback
    # ----------------------------
    def play(self) -> None:
        if self.recording:
            self._post("Stop recording before playback.")
            return
        if self.in_playback:
            self._post("Already playing.")
            return
        if not self.rec or not self.rec.events:
            self._post("Nothing to play – record first or load a macro.")
            return

        loop_forever = self.loop_infinite.get()
        try:
            loop_num = max(1, int(self.loop_count.get()))
        except Exception:
            loop_num = 1

        t = threading.Thread(
            target=self._play_worker,
            args=(loop_forever, loop_num),
            daemon=True,
        )
        t.start()

    def abort(self) -> None:
        if self.in_playback:
            self._post("Abort requested…")
        self.abort_flag = True

    def _play_worker(self, loop_forever: bool, loop_num: int) -> None:
        self.in_playback = True
        self.abort_flag = False
        self._set_status("Playing… (Ctrl+Shift+X to abort)")
        self._post(
            f"Playback starting ({'∞' if loop_forever else loop_num} loop"
            f"{'' if loop_forever or loop_num == 1 else 's'})."
        )

        try:
            count = 0
            while not self.abort_flag and (loop_forever or count < loop_num):
                self._post(f"Playing loop {count + 1}{' (∞)' if loop_forever else ''}…")
                prev_t = 0.0
                for e in self.rec.events:
                    if self.abort_flag:
                        break
                    # Sleep to maintain recorded timing deltas
                    dt = max(0.0, e.t - prev_t)
                    if dt > 0:
                        time.sleep(dt)
                    prev_t = e.t
                    self._play_event(e)

                count += 1
            if self.abort_flag:
                self._post("Playback aborted.")
            else:
                self._post("Playback finished.")
        finally:
            self.in_playback = False
            self._set_status("Idle – Ready")

    def _play_event(self, e: Event) -> None:
        try:
            if e.type == "key_press":
                self._press_key(e.data["key"])
            elif e.type == "key_release":
                self._release_key(e.data["key"])
            elif e.type == "mouse_move":
                self.mouse_ctrl.position = (int(e.data["x"]), int(e.data["y"]))
            elif e.type == "mouse_click":
                btn = Button.left if e.data.get("button") == "left" else Button.right
                if e.data.get("pressed"):
                    self.mouse_ctrl.press(btn)
                else:
                    self.mouse_ctrl.release(btn)
            elif e.type == "mouse_scroll":
                self.mouse_ctrl.scroll(int(e.data.get("dx", 0)), int(e.data.get("dy", 0)))
        except Exception as ex:
            self._post(f"[warn] Failed to play event {e.type}: {ex}")

    def _press_key(self, key_str: str) -> None:
        key = self._str_to_key(key_str)
        self.key_ctrl.press(key)

    def _release_key(self, key_str: str) -> None:
        key = self._str_to_key(key_str)
        self.key_ctrl.release(key)

    @staticmethod
    def _str_to_key(s: str):
        # Convert "Key.space" → Key.space, otherwise literal char
        if s.startswith("Key."):
            name = s.split(".", 1)[1]
            return getattr(Key, name, s)
        return s

    # ----------------------------
    # Save / Load
    # ----------------------------
    def save(self) -> None:
        if not self.rec or not self.rec.events:
            self._post("Nothing to save – record first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Macro JSON", "*.json")],
        )
        if not path:
            return
        payload = {
            "meta": {"name": "Macro", "created": time.strftime("%Y-%m-%d %H:%M:%S")},
            "events": [asdict(ev) for ev in self.rec.events],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            self._post(f"Saved macro to {path}")
        except Exception as ex:
            messagebox.showerror("Save Error", f"Failed to save macro:\n{ex}")

    def load(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Macro JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            events: List[Event] = []
            for e in data.get("events", []):
                events.append(Event(t=float(e["t"]), type=str(e["type"]), data=dict(e["data"])))
            self.rec = Recording(events=events, started_at=time.perf_counter())
            self._post(f"Loaded macro with {len(events)} events from {path}")
            self._set_status("Macro loaded – Ready")
        except Exception as ex:
            messagebox.showerror("Load Error", f"Failed to load macro:\n{ex}")


# ----------------------------
# CLI entrypoint
# ----------------------------
def run():
    import tkinter as tk

    try:
        root = tk.Tk()
    except Exception as e:
        # Helpful error for headless environments
        msg = (
            f"Failed to start Tkinter UI: {e}. "
            "If you are on Linux, ensure Tk is installed "
            "(e.g., 'sudo apt-get install python3-tk')."
        )
        raise SystemExit(msg)

    app = MacroApp(root)
    try:
        root.mainloop()
    finally:
        try:
            app.kb_listener.stop()
            app.ms_listener.stop()
            app.hotkeys.stop()
        except Exception:
            pass

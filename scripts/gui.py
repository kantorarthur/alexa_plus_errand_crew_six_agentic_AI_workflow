"""The small window that opens while you type or speak a request for the Uno.

Button 1 opens it with a text box, button 2 opens it with "Listening...". The window stays
open while the request is being processed and closes when the answer arrives (the answer
itself goes to the Uno's LCD).

What the window says in each situation is decided by screen_for(), a plain function with no
tkinter in it, so it can be tested without a screen. TkUi only draws what screen_for() says.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

TYPING = "typing"
LISTENING = "listening"
TRANSCRIBING = "transcribing"
HEARD = "heard"
SEARCHING = "searching"

CALL_TIMEOUT = 5.0  # seconds to wait for the window thread before giving up
PUMP_MS = 50


@dataclass(frozen=True)
class Screen:
    title: str
    headline: str
    body: str
    hint: str
    editable: bool


def screen_for(mode: str, text: str = "", status: str = "") -> Screen:
    """What the window shows for each mode."""
    if mode == TYPING:
        return Screen("Errand Crew - Type", "Type your request", "",
                      "Press button 1 on the Uno to send", True)
    if mode == LISTENING:
        return Screen("Errand Crew - Listen", "Listening...", "",
                      "Press button 2 on the Uno to stop", False)
    if mode == TRANSCRIBING:
        return Screen("Errand Crew - Listen", "Transcribing...", "", "Please wait", False)
    if mode == HEARD:
        return Screen("Errand Crew - Listen", "Heard:", text or "(nothing)",
                      status or "Sending the request...", False)
    if mode == SEARCHING:
        return Screen("Errand Crew - Type", "Searching...", text,
                      status or "Sending the request...", False)
    raise ValueError(f"unknown mode: {mode}")


class TkUi:
    """The window. Create it and call run() on the main thread; every other method may be
    called from any thread (the serial loop runs on another one)."""

    def __init__(self) -> None:
        import tkinter as tk  # noqa: PLC0415  (imported here so tests of screen_for need no tkinter)

        self._tk = tk
        self._main = threading.current_thread()
        self._jobs: queue.Queue[tuple[Callable[[], Any], list, threading.Event | None]] = queue.Queue()
        self._mode = ""
        self._status = ""

        self._root = tk.Tk()
        self._root.geometry("520x300")
        self._root.minsize(420, 240)
        self._root.protocol("WM_DELETE_WINDOW", self._root.withdraw)
        self._headline = tk.Label(self._root, font=("Segoe UI", 20, "bold"), anchor="w")
        self._headline.pack(fill="x", padx=16, pady=(16, 6))
        self._text = tk.Text(self._root, font=("Segoe UI", 14), wrap="word", height=6)
        self._text.pack(fill="both", expand=True, padx=16, pady=6)
        self._hint = tk.Label(self._root, font=("Segoe UI", 11), anchor="w", fg="#555555")
        self._hint.pack(fill="x", padx=16, pady=(6, 16))
        self._root.withdraw()
        self._root.after(PUMP_MS, self._pump)

    # --- called from any thread -------------------------------------------------

    def typing_started(self) -> None:
        self._call(lambda: self._set(TYPING))

    def listening_started(self) -> None:
        self._call(lambda: self._set(LISTENING))

    def transcribing(self) -> None:
        self._call(lambda: self._set(TRANSCRIBING))

    def heard(self, text: str) -> None:
        self._call(lambda: self._set(HEARD, text))

    def get_typed_text(self) -> str:
        """The text in the box. The window then shows it as the request being searched."""

        def take() -> str:
            text = self._text.get("1.0", "end-1c")
            self._set(SEARCHING, " ".join(text.split()))
            return text

        return self._call(take) or ""

    def status(self, top: str, bottom: str) -> None:
        """What the LCD shows, repeated as a line in the window while a request runs."""
        line = f"{top} {bottom}".strip()
        self._post(lambda: self._set_status(line))

    def cancelled(self, reason: str) -> None:
        self._post(self._hide)

    def answered(self, summary: str) -> None:
        self._post(self._hide)

    def quit(self) -> None:
        self._post(self._root.quit)

    def run(self) -> None:
        self._root.mainloop()

    # --- on the window's own thread ---------------------------------------------

    def _call(self, job: Callable[[], Any]) -> Any:
        """Run job on the window thread and wait for its result."""
        if threading.current_thread() is self._main:
            return job()
        box: list = []
        done = threading.Event()
        self._jobs.put((job, box, done))
        if not done.wait(CALL_TIMEOUT):
            return None
        return box[0] if box else None

    def _post(self, job: Callable[[], Any]) -> None:
        """Run job on the window thread without waiting."""
        if threading.current_thread() is self._main:
            job()
            return
        self._jobs.put((job, [], None))

    def _pump(self) -> None:
        while True:
            try:
                job, box, done = self._jobs.get_nowait()
            except queue.Empty:
                break
            try:
                box.append(job())
            except Exception as exc:  # noqa: BLE001  (a drawing problem must not stop the bridge)
                print(f"Window error: {type(exc).__name__}: {exc}")
            if done is not None:
                done.set()
        self._root.after(PUMP_MS, self._pump)

    def _set(self, mode: str, text: str = "") -> None:
        self._mode = mode
        self._status = ""
        screen = screen_for(mode, text)
        self._root.title(screen.title)
        self._headline.config(text=screen.headline)
        self._hint.config(text=screen.hint)
        self._text.config(state="normal")
        if mode == TYPING or screen.body != self._text.get("1.0", "end-1c"):
            self._text.delete("1.0", "end")
            self._text.insert("1.0", screen.body)
        if not screen.editable:
            self._text.config(state="disabled")
        self._show()
        if screen.editable:
            self._text.focus_force()

    def _set_status(self, line: str) -> None:
        if self._mode not in (HEARD, SEARCHING):
            return
        self._status = line
        self._hint.config(text=line)

    def _show(self) -> None:
        self._root.deiconify()
        self._root.lift()
        self._root.attributes("-topmost", True)  # come to the front, then let go
        self._root.after(300, lambda: self._root.attributes("-topmost", False))

    def _hide(self) -> None:
        self._mode = ""
        self._root.withdraw()

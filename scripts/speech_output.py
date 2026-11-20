"""Reads answers aloud through the PC's speakers (whatever Windows uses as its sound output,
for example a USB speaker). Nothing is installed and nothing leaves the PC: it uses the
voice that comes with the operating system.

  Windows  PowerShell and System.Speech (the voices in Settings > Time & language > Speech)
  macOS    the "say" command
  Linux    espeak-ng or espeak, if installed

The text is given to the voice program on its standard input, never inside the command
line, so whatever the text says it cannot be run as a command.

Try it on its own:

  python scripts/speech_output.py "Evomag has it for 244 lei"

Settings, optional, as environment variables:
  SPEECH_RATE   -10 (slow) to 10 (fast), Windows only. Default 0.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import unicodedata
from collections.abc import Callable
from typing import Any

MAX_CHARS = 1000
POWERSHELL_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.Rate = {rate}; "
    "$s.Speak([Console]::In.ReadToEnd())"
)


def to_ascii(text: str) -> str:
    """Plain ASCII only: the console used to pass the text may not handle accents."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.split())[:MAX_CHARS]


def _rate() -> int:
    try:
        return max(-10, min(10, int(os.environ.get("SPEECH_RATE", "0"))))
    except ValueError:
        return 0


def _start(command: list[str]) -> Callable[[str], Any]:
    def launch(text: str):
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            process.stdin.write(text.encode("ascii"))
            process.stdin.close()
        except OSError:
            pass  # the voice program ended at once; nothing more to do
        return process

    return launch


def default_launcher() -> Callable[[str], Any] | None:
    """A function that starts speaking a text and returns the running process, or None
    when this computer has no voice program we know."""
    if sys.platform.startswith("win"):
        script = POWERSHELL_SCRIPT.format(rate=_rate())  # the rate is an int: safe to insert
        return _start(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    if sys.platform == "darwin":
        return _start(["say"])
    for name in ("espeak-ng", "espeak"):
        path = shutil.which(name)
        if path:
            return _start([path, "--stdin"])
    return None


class Speaker:
    """say() starts reading a text and returns at once; stop() cuts it off."""

    def __init__(self, launcher: Callable[[str], Any] | None = None) -> None:
        self._launcher = launcher if launcher is not None else default_launcher()
        self._lock = threading.Lock()
        self._process = None

    @property
    def available(self) -> bool:
        return self._launcher is not None

    def say(self, text: str) -> None:
        text = to_ascii(text)
        if not text or self._launcher is None:
            return
        self.stop()
        try:
            process = self._launcher(text)
        except OSError as exc:
            print(f"Could not start the voice ({type(exc).__name__}: {exc}).")
            return
        with self._lock:
            self._process = process

    def stop(self) -> None:
        with self._lock:
            process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()

    def wait(self) -> None:
        """Block until the current text has been read (used by the command line test)."""
        with self._lock:
            process = self._process
        if process is not None:
            process.wait()


def main() -> int:
    text = " ".join(sys.argv[1:]) or "Evomag has it for 244 lei, the cheapest of four shops."
    speaker = Speaker()
    if not speaker.available:
        print("No voice program found on this computer.")
        return 2
    print(f'Saying: "{text}"')
    speaker.say(text)
    speaker.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

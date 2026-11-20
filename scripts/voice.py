"""Speech to text for the Uno bridge: record from the PC microphone, turn it into text.

Everything runs on this PC. The recording is given to Whisper (through faster-whisper), an
open speech model, and nothing is sent to any server. The model is downloaded the first time
(about 500 MB for "small") and kept on disk after that.

Try it on its own, without the Uno:

  python scripts/voice.py --list     show the microphones, with their numbers
  python scripts/voice.py --test     press Enter, speak, press Enter: prints what it heard

Settings, all optional, as environment variables:
  VOICE_MODEL     tiny, base, small (default), medium. Bigger is more exact and slower.
  VOICE_LANGUAGE  ro, en, ... Fixing it avoids wrong guesses on short phrases. Default: detect.
  VOICE_DEVICE    microphone number from --list. Default: the system default.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import threading
from collections.abc import Callable
from typing import Any

SAMPLE_RATE = 16000  # what Whisper expects
MIN_SECONDS = 0.4  # shorter than this is a mis-press, not a request
SILENCE_PEAK = 0.01  # a recording quieter than this is silence; Whisper invents words from it
MAX_SECONDS = 60
DEFAULT_MODEL = "small"
REQUIRED = {"numpy": "numpy", "sounddevice": "sounddevice", "faster_whisper": "faster-whisper"}


def missing_packages() -> list[str]:
    """pip names of the packages voice input needs that are not installed."""
    return [pip for module, pip in REQUIRED.items() if importlib.util.find_spec(module) is None]


def resample(audio, from_rate: int, to_rate: int = SAMPLE_RATE):
    """Linear resampling, for microphones that cannot record at 16 kHz."""
    import numpy as np  # noqa: PLC0415

    if from_rate == to_rate or len(audio) == 0:
        return audio
    length = int(len(audio) * to_rate / from_rate)
    positions = np.linspace(0, len(audio) - 1, num=length)
    return np.interp(positions, np.arange(len(audio)), audio).astype("float32")


def _load_whisper(size: str):
    from faster_whisper import WhisperModel  # noqa: PLC0415

    return WhisperModel(size, device="cpu", compute_type="int8")


def _open_stream(callback: Callable[[Any], None], device):
    """Open the microphone. Returns (stream, sample_rate). Tries 16 kHz, else the mic's own rate."""
    import sounddevice as sd  # noqa: PLC0415

    def on_audio(indata, frames, time_info, status) -> None:
        callback(indata[:, 0])

    try:
        rate = SAMPLE_RATE
        stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                device=device, callback=on_audio)
    except sd.PortAudioError:
        rate = int(sd.query_devices(device, "input")["default_samplerate"])
        stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                device=device, callback=on_audio)
    return stream, rate


class Voice:
    """start() opens the microphone, stop() closes it and returns what was said as text."""

    def __init__(self, model_size: str | None = None, language: str | None = None,
                 device: int | str | None = None, model_factory=None, stream_factory=None) -> None:
        self._model_size = model_size or os.environ.get("VOICE_MODEL") or DEFAULT_MODEL
        self._language = language or os.environ.get("VOICE_LANGUAGE") or None
        if device is None:
            raw = os.environ.get("VOICE_DEVICE", "")
            device = int(raw) if raw.isdigit() else (raw or None)
        self._device = device
        self._model_factory = model_factory or _load_whisper
        self._stream_factory = stream_factory or _open_stream
        self._model = None
        self._model_lock = threading.Lock()
        self._lock = threading.Lock()
        self._chunks: list = []
        self._samples = 0
        self._stream = None
        self._rate = SAMPLE_RATE

    def warm_up(self) -> None:
        """Load the model now, so the first request does not wait for it."""
        self._get_model()

    def start(self) -> None:
        self._close_stream()
        with self._lock:
            self._chunks = []
            self._samples = 0
        stream, rate = self._stream_factory(self._on_audio, self._device)
        self._rate = rate
        self._stream = stream
        stream.start()

    def stop(self) -> str:
        audio = self._finish()
        if audio is None:
            return ""
        segments, _info = self._get_model().transcribe(
            audio, language=self._language, beam_size=5, vad_filter=True
        )
        return " ".join(" ".join(segment.text.split()) for segment in segments).strip()

    def cancel(self) -> None:
        self._finish()

    # --- internals ----------------------------------------------------------------

    def _on_audio(self, chunk) -> None:
        with self._lock:
            if self._samples >= MAX_SECONDS * self._rate:
                return
            self._chunks.append(chunk.copy())
            self._samples += len(chunk)

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:  # noqa: BLE001
                print(f"Could not close the microphone cleanly ({type(exc).__name__}).")

    def _finish(self):
        """Close the microphone and return the recording at 16 kHz, or None if unusable."""
        import numpy as np  # noqa: PLC0415

        self._close_stream()
        with self._lock:
            chunks, self._chunks, self._samples = self._chunks, [], 0
        if not chunks:
            return None
        audio = resample(np.concatenate(chunks).astype("float32"), self._rate)
        if len(audio) < MIN_SECONDS * SAMPLE_RATE:
            return None
        if float(np.max(np.abs(audio))) < SILENCE_PEAK:
            return None
        return audio

    def _get_model(self):
        with self._model_lock:
            if self._model is None:
                self._model = self._model_factory(self._model_size)
            return self._model


def _list_devices() -> None:
    import sounddevice as sd  # noqa: PLC0415

    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0:
            print(f"  {index}: {info['name']}")
    print("Use one with:  $env:VOICE_DEVICE = \"<number>\"")


def _test() -> None:
    voice = Voice()
    print(f"Loading the speech model ({voice._model_size}); the first time it is downloaded...")
    voice.warm_up()
    print("Ready.")
    input("Press Enter, then speak. ")
    voice.start()
    input("Listening... press Enter to stop. ")
    print("Transcribing...")
    text = voice.stop()
    print(f'Heard: "{text}"' if text else "Heard nothing.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Microphone and speech-to-text check")
    parser.add_argument("--list", action="store_true", help="list the microphones")
    parser.add_argument("--test", action="store_true", help="record once and print the text")
    args = parser.parse_args()
    missing = missing_packages()
    if missing:
        print("Install first:  pip install " + " ".join(missing))
        return 2
    if args.list:
        _list_devices()
        return 0
    if args.test:
        _test()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Voice input with a fake microphone and a fake speech model (no sound card, no download)."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "voice.py"
spec = importlib.util.spec_from_file_location("uno_voice", SCRIPT)
voice_module = importlib.util.module_from_spec(spec)
sys.modules["uno_voice"] = voice_module
spec.loader.exec_module(voice_module)

RATE = voice_module.SAMPLE_RATE


class FakeStream:
    def __init__(self):
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


class FakeModel:
    def __init__(self, words=("cheapest samsung tv",)):
        self.words = words
        self.heard = []

    def transcribe(self, audio, **options):
        self.heard.append((len(audio), options))
        return iter([SimpleNamespace(text=f"  {w} ") for w in self.words]), None


class Rig:
    """A Voice wired to a fake microphone (feed() plays sound into it) and a fake model."""

    def __init__(self, words=("cheapest samsung tv",), rate=RATE, **kwargs):
        self.model = FakeModel(words)
        self.streams = []
        self.loads = 0
        self._callback = None
        self.rate = rate

        def model_factory(size):
            self.loads += 1
            self.size = size
            return self.model

        def stream_factory(callback, device):
            self._callback = callback
            self.device = device
            stream = FakeStream()
            self.streams.append(stream)
            return stream, self.rate

        self.voice = voice_module.Voice(model_factory=model_factory, stream_factory=stream_factory, **kwargs)

    def feed(self, seconds, loudness=0.3):
        samples = int(seconds * self.rate)
        self._callback((np.ones(samples, dtype="float32") * loudness))


def test_speech_is_recorded_and_turned_into_text():
    rig = Rig()
    rig.voice.start()
    assert rig.streams[0].started
    rig.feed(1.0)
    assert rig.voice.stop() == "cheapest samsung tv"
    assert rig.streams[0].closed
    assert rig.model.heard[0][0] == RATE


def test_several_segments_are_joined_with_single_spaces():
    rig = Rig(words=("cel mai   ieftin", "laptop"))
    rig.voice.start()
    rig.feed(1.0)
    assert rig.voice.stop() == "cel mai ieftin laptop"


def test_a_recording_that_is_too_short_is_not_transcribed():
    rig = Rig()
    rig.voice.start()
    rig.feed(0.1)
    assert rig.voice.stop() == ""
    assert rig.loads == 0


def test_silence_is_not_transcribed_because_whisper_invents_words_from_it():
    rig = Rig()
    rig.voice.start()
    rig.feed(2.0, loudness=0.0)
    assert rig.voice.stop() == ""
    assert rig.model.heard == []


def test_stop_without_start_gives_nothing():
    assert Rig().voice.stop() == ""


def test_cancel_throws_the_recording_away_and_frees_the_microphone():
    rig = Rig()
    rig.voice.start()
    rig.feed(1.0)
    rig.voice.cancel()
    assert rig.streams[0].closed
    assert rig.voice.stop() == ""
    assert rig.model.heard == []


def test_a_second_recording_does_not_contain_the_first():
    rig = Rig()
    rig.voice.start()
    rig.feed(1.0)
    rig.voice.stop()
    rig.voice.start()
    rig.feed(2.0)
    rig.voice.stop()
    assert [n for n, _ in rig.model.heard] == [RATE, 2 * RATE]


def test_starting_twice_closes_the_first_microphone_stream():
    rig = Rig()
    rig.voice.start()
    rig.voice.start()
    assert rig.streams[0].closed
    assert len(rig.streams) == 2


def test_the_model_is_loaded_once():
    rig = Rig()
    rig.voice.warm_up()
    for _ in range(2):
        rig.voice.start()
        rig.feed(1.0)
        rig.voice.stop()
    assert rig.loads == 1


def test_a_microphone_at_another_rate_is_resampled_to_16_khz():
    rig = Rig(rate=48000)
    rig.voice.start()
    rig.feed(1.0)
    rig.voice.stop()
    assert rig.model.heard[0][0] == RATE


def test_recording_stops_growing_after_the_maximum_length():
    rig = Rig()
    rig.voice.start()
    for _ in range(voice_module.MAX_SECONDS + 10):
        rig.feed(1.0)
    rig.voice.stop()
    assert rig.model.heard[0][0] <= voice_module.MAX_SECONDS * RATE


def test_language_and_model_come_from_arguments_or_the_environment(monkeypatch):
    rig = Rig(model_size="base", language="ro")
    rig.voice.warm_up()
    rig.voice.start()
    rig.feed(1.0)
    rig.voice.stop()
    assert rig.size == "base"
    assert rig.model.heard[0][1]["language"] == "ro"

    monkeypatch.setenv("VOICE_MODEL", "tiny")
    monkeypatch.setenv("VOICE_LANGUAGE", "en")
    monkeypatch.setenv("VOICE_DEVICE", "3")
    env_rig = Rig()
    env_rig.voice.warm_up()
    env_rig.voice.start()
    assert (env_rig.size, env_rig.device) == ("tiny", 3)
    env_rig.feed(1.0)
    env_rig.voice.stop()
    assert env_rig.model.heard[0][1]["language"] == "en"


def test_resample_keeps_the_length_in_seconds():
    audio = np.zeros(48000, dtype="float32")
    assert len(voice_module.resample(audio, 48000)) == RATE
    assert voice_module.resample(audio, RATE) is audio


def test_missing_packages_lists_pip_names(monkeypatch):
    monkeypatch.setattr(voice_module.importlib.util, "find_spec", lambda name: None)
    assert voice_module.missing_packages() == ["numpy", "sounddevice", "faster-whisper"]

"""Reading answers aloud: starting, stopping, and that text is never run as a command."""

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "speech_output.py"
spec = importlib.util.spec_from_file_location("uno_speech_output", SCRIPT)
speech = importlib.util.module_from_spec(spec)
sys.modules["uno_speech_output"] = speech
spec.loader.exec_module(speech)


class FakeProcess:
    def __init__(self):
        self.terminated = 0
        self.finished = False

    def poll(self):
        return 0 if self.finished else None

    def terminate(self):
        self.terminated += 1
        self.finished = True


class Launcher:
    def __init__(self, fail=False):
        self.texts = []
        self.processes = []
        self.fail = fail

    def __call__(self, text):
        if self.fail:
            raise FileNotFoundError("powershell")
        self.texts.append(text)
        process = FakeProcess()
        self.processes.append(process)
        return process


def test_say_starts_the_voice_with_the_text():
    launcher = Launcher()
    speech.Speaker(launcher).say("Evomag has it for 244 lei.")
    assert launcher.texts == ["Evomag has it for 244 lei."]


def test_accents_are_folded_and_whitespace_collapsed():
    launcher = Launcher()
    speech.Speaker(launcher).say("  Televizor   ieftin și bun \n")
    assert launcher.texts == ["Televizor ieftin si bun"]


def test_a_very_long_text_is_cut():
    launcher = Launcher()
    speech.Speaker(launcher).say("a" * 5000)
    assert len(launcher.texts[0]) == speech.MAX_CHARS


def test_empty_text_says_nothing():
    launcher = Launcher()
    speaker = speech.Speaker(launcher)
    speaker.say("")
    speaker.say("   ")
    speaker.say("§ ¶")
    assert launcher.texts == []


def test_a_new_text_cuts_off_the_old_one():
    launcher = Launcher()
    speaker = speech.Speaker(launcher)
    speaker.say("first")
    speaker.say("second")
    assert launcher.processes[0].terminated == 1
    assert launcher.processes[1].terminated == 0


def test_stop_cuts_the_voice_and_a_second_stop_does_nothing():
    launcher = Launcher()
    speaker = speech.Speaker(launcher)
    speaker.say("hello")
    speaker.stop()
    speaker.stop()
    assert launcher.processes[0].terminated == 1


def test_stop_does_not_touch_a_voice_that_already_finished():
    launcher = Launcher()
    speaker = speech.Speaker(launcher)
    speaker.say("hello")
    launcher.processes[0].finished = True
    speaker.stop()
    assert launcher.processes[0].terminated == 0


def test_stop_with_nothing_playing_is_fine():
    speech.Speaker(Launcher()).stop()


def test_without_a_voice_program_everything_is_a_no_op(monkeypatch):
    monkeypatch.setattr(speech, "default_launcher", lambda: None)
    speaker = speech.Speaker()
    assert not speaker.available
    speaker.say("hello")
    speaker.stop()


def test_a_voice_program_that_cannot_start_does_not_break_the_bridge(capsys):
    speaker = speech.Speaker(Launcher(fail=True))
    speaker.say("hello")
    assert "Could not start the voice" in capsys.readouterr().out
    speaker.stop()


# --- real processes ---------------------------------------------------------------


def test_a_real_voice_process_is_really_stopped():
    launch = speech._start([sys.executable, "-c", "import sys, time; sys.stdin.read(); time.sleep(60)"])
    speaker = speech.Speaker(launch)
    speaker.say("hello")
    process = speaker._process
    assert process.poll() is None
    speaker.stop()
    assert process.wait(timeout=5) is not None


def test_text_reaches_the_program_on_stdin_and_is_never_run_as_a_command(tmp_path):
    out = tmp_path / "heard.txt"
    code = f"import sys; open({str(out)!r}, 'w').write(sys.stdin.read())"
    launch = speech._start([sys.executable, "-c", code])
    attack = '"; touch /tmp/pwned; $(whoami) `id` | cat & echo done'
    speaker = speech.Speaker(launch)
    speaker.say(attack)
    speaker.wait()
    assert out.read_text() == speech.to_ascii(attack)


# --- choosing the voice program ---------------------------------------------------


class Captured:
    def __init__(self):
        self.args = None
        self.written = b""
        outer = self

        class Stdin:
            def write(self, data):
                outer.written += data

            def close(self):
                pass

        class Process:
            stdin = Stdin()

        self.process = Process()

    def popen(self, args, **kwargs):
        self.args = args
        return self.process


def _windows_command(monkeypatch, rate=None):
    captured = Captured()
    monkeypatch.setattr(speech.sys, "platform", "win32")
    monkeypatch.setattr(speech.subprocess, "Popen", captured.popen)
    if rate is None:
        monkeypatch.delenv("SPEECH_RATE", raising=False)
    else:
        monkeypatch.setenv("SPEECH_RATE", rate)
    launch = speech.default_launcher()
    launch('Say "this" $(whoami)')
    return captured


def test_on_windows_powershell_is_used_and_the_text_is_not_in_the_command(monkeypatch):
    captured = _windows_command(monkeypatch)
    assert captured.args[0] == "powershell"
    assert "System.Speech" in captured.args[-1]
    assert "whoami" not in " ".join(captured.args)
    assert captured.written == b'Say "this" $(whoami)'


@pytest.mark.parametrize(
    "setting, expected",
    [(None, 0), ("3", 3), ("-4", -4), ("99", 10), ("-99", -10), ("fast", 0), ("0; Remove-Item x", 0)],
)
def test_the_speech_rate_is_always_a_small_integer(monkeypatch, setting, expected):
    captured = _windows_command(monkeypatch, setting)
    assert f"$s.Rate = {expected};" in captured.args[-1]
    assert "Remove-Item" not in captured.args[-1]


def test_on_a_mac_the_say_command_is_used(monkeypatch):
    captured = Captured()
    monkeypatch.setattr(speech.sys, "platform", "darwin")
    monkeypatch.setattr(speech.subprocess, "Popen", captured.popen)
    speech.default_launcher()("hello")
    assert captured.args == ["say"]


def test_on_linux_espeak_is_used_when_it_exists_and_nothing_otherwise(monkeypatch):
    monkeypatch.setattr(speech.sys, "platform", "linux")
    monkeypatch.setattr(speech.shutil, "which", lambda name: None)
    assert speech.default_launcher() is None
    captured = Captured()
    monkeypatch.setattr(speech.shutil, "which", lambda name: "/usr/bin/espeak-ng" if name == "espeak-ng" else None)
    monkeypatch.setattr(speech.subprocess, "Popen", captured.popen)
    speech.default_launcher()("hello")
    assert captured.args == ["/usr/bin/espeak-ng", "--stdin"]

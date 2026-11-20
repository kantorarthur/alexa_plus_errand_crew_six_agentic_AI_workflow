"""The Uno bridge: which button does what, with a fake LCD, fake voice and fake serial cable."""

import importlib.util
import sys
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "uno_bridge.py"
spec = importlib.util.spec_from_file_location("uno_bridge", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
sys.modules["uno_bridge"] = bridge  # dataclasses and pickling look modules up by name
spec.loader.exec_module(bridge)


class FakeDisplay:
    def __init__(self):
        self.screens = []
        self.ready_calls = 0

    def show(self, top, bottom=""):
        self.screens.append((top, bottom))

    def ready(self):
        self.ready_calls += 1


class FakeVoice:
    def __init__(self, text="cheapest samsung tv", fail_start=False, fail_stop=False):
        self.text = text
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.started = 0
        self.stopped = 0
        self.cancelled = 0

    def start(self):
        if self.fail_start:
            raise OSError("no microphone")
        self.started += 1

    def stop(self):
        self.stopped += 1
        if self.fail_stop:
            raise RuntimeError("model failed")
        return self.text

    def cancel(self):
        self.cancelled += 1


class RecordingUi(bridge.ConsoleUi):
    """The terminal UI, plus a log of every call the window would have received."""

    def __init__(self):
        super().__init__()
        self.log = []

    def typing_started(self):
        self.log.append("typing_started")
        super().typing_started()

    def listening_started(self):
        self.log.append("listening_started")
        super().listening_started()

    def transcribing(self):
        self.log.append("transcribing")
        super().transcribing()

    def heard(self, text):
        self.log.append(("heard", text))
        super().heard(text)

    def status(self, top, bottom):
        self.log.append(("status", top, bottom))

    def cancelled(self, reason):
        self.log.append(("cancelled", reason))
        super().cancelled(reason)

    def answered(self, summary):
        self.log.append(("answered", summary))


SAMPLE_RESULT = {
    "status": "done",
    "spoken_summary": "Evomag has it for 244 lei, the cheapest of four shops.",
    "sites": [
        {"site_id": "altex", "status": "ok", "offers": [{"price": 259.99, "currency": "RON"}]},
        {"site_id": "evomag", "status": "ok", "offers": [{"price": 244.0, "currency": "RON"}]},
        {"site_id": "vexio", "status": "empty", "offers": []},
        {"site_id": "mediagalaxy", "status": "ok", "offers": [{"price": 2499, "currency": "RON"}]},
    ],
}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make(voice="default"):
    display = FakeDisplay()
    ui = RecordingUi()
    clock = Clock()
    voice = FakeVoice() if voice == "default" else voice
    session = bridge.Session(display, ui, voice, clock=clock, sleep=lambda _s: None, timeout=60)
    return session, display, ui, voice, clock


# --- button 1: text -------------------------------------------------------------


def test_button_1_starts_typing_and_the_second_press_sends_what_was_typed():
    session, display, ui, _voice, _clock = make()
    assert session.press("1") is None
    assert session.state == bridge.TYPING
    ui.feed("cheapest samsung")
    ui.feed("tv")
    assert session.press("1") == "cheapest samsung tv"
    assert session.state == bridge.PROCESSING


def test_typing_nothing_gives_no_request_and_returns_to_idle():
    session, display, _ui, _voice, _clock = make()
    session.press("1")
    assert session.press("1") is None
    assert session.state == bridge.IDLE
    assert ("Not understood", "Try again") in display.screens
    assert display.ready_calls == 1


def test_text_typed_before_button_1_is_not_used():
    session, _display, ui, _voice, _clock = make()
    ui.feed("this was typed too early")
    session.press("1")
    assert session.press("1") is None


def test_a_long_request_is_cut_to_the_server_limit():
    session, _display, ui, _voice, _clock = make()
    session.press("1")
    ui.feed("a" * 500)
    assert len(session.press("1")) == bridge.MAX_REQUEST_CHARS


# --- button 2: voice ------------------------------------------------------------


def test_button_2_listens_and_the_second_press_sends_the_transcript():
    session, display, _ui, voice, _clock = make()
    assert session.press("2") is None
    assert session.state == bridge.LISTENING
    assert voice.started == 1
    assert session.press("2") == "cheapest samsung tv"
    assert voice.stopped == 1
    assert session.state == bridge.PROCESSING
    assert ("Heard:", "cheapest samsung tv") in display.screens


def test_speech_that_gives_no_text_sends_nothing():
    session, display, _ui, _voice, _clock = make(FakeVoice(text="  "))
    session.press("2")
    assert session.press("2") is None
    assert session.state == bridge.IDLE
    assert ("Not understood", "Try again") in display.screens


def test_a_failing_speech_model_does_not_break_the_session():
    session, _display, _ui, _voice, _clock = make(FakeVoice(fail_stop=True))
    session.press("2")
    assert session.press("2") is None
    assert session.state == bridge.IDLE


def test_a_missing_microphone_does_not_break_the_session():
    session, display, _ui, _voice, _clock = make(FakeVoice(fail_start=True))
    assert session.press("2") is None
    assert session.state == bridge.IDLE
    assert ("Mic error", "Check the PC") in display.screens


def test_without_the_voice_module_button_2_says_so_and_stays_idle():
    session, display, _ui, _voice, _clock = make(voice=None)
    assert session.press("2") is None
    assert session.state == bridge.IDLE
    assert ("No voice input", "Not installed") in display.screens


# --- presses that must do nothing -----------------------------------------------


@pytest.mark.parametrize("button", ["5", "9", ""])
def test_other_buttons_do_nothing_when_idle(button):
    session, display, _ui, _voice, _clock = make()
    assert session.press(button) is None
    assert session.state == bridge.IDLE


def test_the_other_button_is_ignored_while_typing_or_listening():
    session, _display, _ui, voice, _clock = make()
    session.press("1")
    assert session.press("2") is None
    assert session.state == bridge.TYPING
    assert voice.started == 0
    session.press("1")  # nothing typed: back to idle
    session.press("2")
    assert session.press("1") is None
    assert session.state == bridge.LISTENING


def test_presses_are_ignored_while_the_request_is_being_processed():
    session, _display, ui, voice, _clock = make()
    session.press("1")
    ui.feed("cheapest laptop")
    assert session.press("1") == "cheapest laptop"
    assert session.press("1") is None
    assert session.press("2") is None
    assert voice.started == 0
    session.finish()
    assert session.state == bridge.IDLE


# --- timeouts -------------------------------------------------------------------


def test_forgotten_typing_times_out():
    session, display, _ui, _voice, clock = make()
    session.press("1")
    clock.now = 59
    session.tick()
    assert session.state == bridge.TYPING
    clock.now = 61
    session.tick()
    assert session.state == bridge.IDLE
    assert ("Timeout", "Try again") in display.screens


def test_forgotten_listening_times_out_and_frees_the_microphone():
    session, _display, _ui, voice, clock = make()
    session.press("2")
    clock.now = 61
    session.tick()
    assert session.state == bridge.IDLE
    assert voice.cancelled == 1


def test_tick_does_nothing_while_idle_or_processing():
    session, display, ui, _voice, clock = make()
    clock.now = 1000
    session.tick()
    session.press("1")
    ui.feed("cheapest laptop")
    session.press("1")
    clock.now = 5000
    session.tick()
    assert session.state == bridge.PROCESSING


# --- the serial line ------------------------------------------------------------


@pytest.mark.parametrize(
    "line, expected",
    [("ASK:1\n", "1"), ("ASK:2\r\n", "2"), ("ASK: 3 \n", "3"), ("ASK:7\n", None),
     ("ASK:\n", None), ("hello\n", None), ("", None), ("ASK:samsung tv\n", None)],
)
def test_parse_press(line, expected):
    assert bridge.parse_press(line) == expected


class ScriptedPort:
    """A serial cable that plays back a script. A step is a line to 'receive' or a function
    to run first (for example, to type text as if at the keyboard)."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.written = []
        self.input_flushed = 0

    def readline(self):
        while self.steps:
            step = self.steps.pop(0)
            if callable(step):
                step()
                continue
            return step.encode("ascii")
        raise KeyboardInterrupt

    def write(self, data):
        self.written.append(data)

    def reset_input_buffer(self):
        self.input_flushed += 1


def _run_serve(monkeypatch, steps_for, voice=None, answer="Evomag has it for 1.999 lei.", speaker=None):
    asked = []

    async def fake_ask(request, url, token, display, memory=None):
        asked.append(request)
        if memory is not None:
            memory.remember(SAMPLE_RESULT)
        return answer

    monkeypatch.setattr(bridge, "ask_server", fake_ask)
    monkeypatch.setattr(bridge, "PAGE_SECONDS", 0)
    ui = RecordingUi()
    port = ScriptedPort(steps_for(ui))
    session = bridge.Session(bridge.Display(port), ui, voice, sleep=lambda _s: None,
                             flush=port.reset_input_buffer, speaker=speaker)
    with pytest.raises(KeyboardInterrupt):
        bridge.serve(port, "http://x/mcp", "tok", ui, voice, session=session)
    return asked, port, session, ui


def test_serve_text_request_end_to_end(monkeypatch):
    asked, port, session, ui = _run_serve(
        monkeypatch,
        lambda ui: ["ASK:1\n", lambda: ui.feed("cheapest samsung tv"), "ASK:1\n"],
    )
    assert asked == ["cheapest samsung tv"]
    assert b"R\n" in port.written
    assert port.input_flushed == 1
    assert session.state == bridge.IDLE


def test_serve_voice_request_end_to_end(monkeypatch):
    asked, port, session, ui = _run_serve(
        monkeypatch, lambda ui: ["ASK:2\n", "ASK:2\n"], voice=FakeVoice("cheapest laptop"),
    )
    assert asked == ["cheapest laptop"]
    assert port.input_flushed == 1
    assert session.state == bridge.IDLE


def test_serve_buttons_3_and_4_after_a_request_do_nothing(monkeypatch):
    asked, _port, session, _ui = _run_serve(
        monkeypatch,
        lambda ui: ["ASK:1\n", lambda: ui.feed("cheapest tv"), "ASK:1\n", "ASK:3\n", "ASK:4\n"],
    )
    assert asked == ["cheapest tv"]
    assert session.state == bridge.IDLE


def test_serve_ignores_noise_on_the_cable(monkeypatch):
    asked, _port, _session, _ui = _run_serve(
        monkeypatch, lambda ui: ["garbage\n", "\n", "ASK:9\n", "ASK:3\n"],
    )
    assert asked == []


def test_a_server_failure_still_returns_the_session_to_idle(monkeypatch):
    async def boom(request, url, token, display, memory=None):
        raise ConnectionError("down")

    monkeypatch.setattr(bridge, "ask_server", boom)
    monkeypatch.setattr(bridge, "PAGE_SECONDS", 0)
    ui = bridge.ConsoleUi()
    port = ScriptedPort(["ASK:1\n", lambda: ui.feed("cheapest tv"), "ASK:1\n"])
    session = bridge.Session(bridge.Display(port), ui, None, sleep=lambda _s: None,
                             flush=port.reset_input_buffer)
    with pytest.raises(KeyboardInterrupt):
        bridge.serve(port, "http://x/mcp", "tok", ui, None, session=session)
    assert session.state == bridge.IDLE
    assert b"R\n" in port.written


# --- what the window is told ------------------------------------------------------


def test_the_window_hears_about_listening_transcribing_and_the_words_in_order():
    session, _display, ui, _voice, _clock = make()
    session.press("2")
    session.press("2")
    assert ui.log == ["listening_started", "transcribing", ("heard", "cheapest samsung tv")]


def test_the_window_is_closed_when_nothing_was_understood():
    session, _display, ui, _voice, _clock = make(FakeVoice(text=""))
    session.press("2")
    session.press("2")
    assert ("cancelled", "Not understood") in ui.log


def test_the_window_is_closed_when_typing_times_out():
    session, _display, ui, _voice, clock = make()
    session.press("1")
    clock.now = 61
    session.tick()
    assert ("cancelled", "Timeout") in ui.log


def test_the_window_is_closed_when_the_answer_arrives(monkeypatch):
    _asked, _port, _session, ui = _run_serve(
        monkeypatch,
        lambda ui: ["ASK:1\n", lambda: ui.feed("cheapest tv"), "ASK:1\n"],
        answer="Evomag has it.",
    )
    assert ("answered", "Evomag has it.") in ui.log


def test_the_window_is_closed_even_when_the_server_fails(monkeypatch):
    async def boom(request, url, token, display, memory=None):
        raise ConnectionError("down")

    monkeypatch.setattr(bridge, "ask_server", boom)
    monkeypatch.setattr(bridge, "PAGE_SECONDS", 0)
    ui = RecordingUi()
    port = ScriptedPort(["ASK:1\n", lambda: ui.feed("cheapest tv"), "ASK:1\n"])
    session = bridge.Session(bridge.Display(port), ui, None, sleep=lambda _s: None,
                             flush=port.reset_input_buffer)
    with pytest.raises(KeyboardInterrupt):
        bridge.serve(port, "http://x/mcp", "tok", ui, None, session=session)
    assert any(entry[0] == "answered" for entry in ui.log if isinstance(entry, tuple))


def test_everything_shown_on_the_lcd_is_also_given_to_the_window(monkeypatch):
    _asked, _port, _session, ui = _run_serve(
        monkeypatch,
        lambda ui: ["ASK:1\n", lambda: ui.feed("cheapest tv"), "ASK:1\n"],
    )
    statuses = [entry for entry in ui.log if isinstance(entry, tuple) and entry[0] == "status"]
    assert ("status", "Asking...", "cheapest tv") in statuses


# --- loading the voice module ---------------------------------------------------


def _fake_voice_module(missing):
    import types

    module = types.ModuleType("voice")
    module.missing_packages = lambda: missing

    class Voice:
        warmed = threading.Event()

        def warm_up(self):
            Voice.warmed.set()

    module.Voice = Voice
    return module


def test_make_voice_returns_none_and_says_what_to_install(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "voice", _fake_voice_module(["faster-whisper"]))
    assert bridge.make_voice() is None
    assert "pip install faster-whisper" in capsys.readouterr().out


def test_make_voice_returns_a_recorder_and_loads_the_model_in_the_background(monkeypatch):
    module = _fake_voice_module([])
    monkeypatch.setitem(sys.modules, "voice", module)
    recorder = bridge.make_voice()
    assert isinstance(recorder, module.Voice)
    assert module.Voice.warmed.wait(2)


def test_make_voice_survives_a_failing_model_download(monkeypatch, capsys):
    module = _fake_voice_module([])

    def broken(self):
        raise ConnectionError("offline")

    module.Voice.warm_up = broken
    monkeypatch.setitem(sys.modules, "voice", module)
    assert bridge.make_voice() is not None
    import time

    for _ in range(40):
        if "Could not load the speech model" in capsys.readouterr().out:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the failure was not reported")


def test_every_fixed_lcd_text_fits_the_16_character_screen():
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    texts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("show", "_back_to_idle"):
                texts += [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    assert len(texts) >= 12
    assert [text for text in texts if len(text) > bridge.LCD_WIDTH] == []


# --- buttons 3 and 4: repeat and details ------------------------------------------


def _session_with_answer():
    display = FakeDisplay()
    ui = RecordingUi()
    flushed = []
    session = bridge.Session(display, ui, None, sleep=lambda _s: None, page_seconds=0,
                             flush=lambda: flushed.append(1))
    session.memory.remember(SAMPLE_RESULT)
    return session, display, flushed


def test_shop_line_looks_like_the_example():
    site = {"site_id": "evomag", "status": "ok", "offers": [{"price": 244.0, "currency": "RON"}]}
    assert bridge.shop_line(site) == "evomag 244 lei"


@pytest.mark.parametrize(
    "site, expected",
    [
        ({"site_id": "altex", "offers": [{"price": 259.99, "currency": "RON"}]}, "altex 260 lei"),
        ({"site_id": "mediagalaxy", "offers": [{"price": 2499, "currency": "RON"}]}, "mediagalaxy 2499"),
        ({"site_id": "mediagalaxy", "offers": [{"price": 12499, "currency": "RON"}]}, "mediagalax 12499"),
        ({"site_id": "vexio", "offers": [{"price": 80, "currency": "EUR"}]}, "vexio 80 EUR"),
        ({"site_id": "vexio", "status": "empty", "offers": []}, "vexio none"),
        ({"site_id": "altex", "status": "blocked", "offers": []}, "altex blocked"),
        ({"site_id": "mediagalaxy", "status": "blocked", "offers": []}, "mediagal blocked"),
        ({"site_id": "evomag", "status": "error"}, "evomag error"),
    ],
)
def test_shop_line_cases(site, expected):
    line = bridge.shop_line(site)
    assert line == expected
    assert len(line) <= bridge.LCD_WIDTH


def test_every_shop_line_fits_the_screen_for_any_price():
    for price in (0.5, 9, 99.99, 1234.5, 99999, 123456.78):
        for site_id in ("evomag", "altex", "mediagalaxy", "vexio"):
            line = bridge.shop_line({"site_id": site_id, "offers": [{"price": price, "currency": "RON"}]})
            assert len(line) <= bridge.LCD_WIDTH, line


def test_shops_are_listed_cheapest_first_and_the_empty_ones_last():
    assert bridge.shop_lines(SAMPLE_RESULT["sites"]) == [
        "evomag 244 lei", "altex 260 lei", "mediagalaxy 2499", "vexio none",
    ]


def test_a_failed_result_is_not_remembered():
    memory = bridge.LastAnswer()
    memory.remember(SAMPLE_RESULT)
    memory.remember({"status": "failed", "spoken_summary": "Sorry, I could not finish that errand."})
    assert memory.summary is None
    assert memory.shops == []


def test_button_3_shows_the_last_answer_again_page_by_page():
    session, display, flushed = _session_with_answer()
    assert session.press("3") is None
    expected = bridge.pages(SAMPLE_RESULT["spoken_summary"])
    assert display.screens[: len(expected)] == expected
    assert session.state == bridge.IDLE
    assert flushed == [1]
    assert display.screens[-1] == ("1=text 2=voice", "3=repeat 4=more")


def test_button_4_shows_two_shops_per_screen():
    session, display, flushed = _session_with_answer()
    session.press("4")
    assert display.screens[:2] == [
        ("evomag 244 lei", "altex 260 lei"),
        ("mediagalaxy 2499", "vexio none"),
    ]
    assert session.state == bridge.IDLE
    assert flushed == [1]


def test_an_odd_number_of_shops_leaves_the_last_row_empty():
    session, display, _flushed = _session_with_answer()
    session.memory.shops = ["evomag 244 lei", "altex 260 lei", "vexio none"]
    session.press("4")
    assert display.screens[1] == ("vexio none", "")


def test_repeat_and_details_say_so_when_there_is_nothing_yet():
    session, display, _ui, _voice, _clock = make()
    session.press("3")
    session.press("4")
    assert ("Nothing to", "repeat yet") in display.screens
    assert ("No details yet", "Ask first") in display.screens
    assert session.state == bridge.IDLE


def test_buttons_3_and_4_are_ignored_while_typing_listening_or_processing():
    session, display, _ui, _voice, _clock = make()
    session.memory.remember(SAMPLE_RESULT)
    session.press("1")
    shown = len(display.screens)
    session.press("3")
    session.press("4")
    assert len(display.screens) == shown
    session.press("1")  # nothing typed: back to idle
    session.press("2")
    shown = len(display.screens)
    session.press("3")
    session.press("4")
    assert len(display.screens) == shown
    assert session.state == bridge.LISTENING


def test_serve_buttons_3_and_4_replay_the_answer_of_the_last_request(monkeypatch):
    _asked, port, session, _ui = _run_serve(
        monkeypatch,
        lambda ui: ["ASK:1\n", lambda: ui.feed("cheapest tv"), "ASK:1\n", "ASK:3\n", "ASK:4\n"],
    )
    sent = b"".join(port.written)
    assert sent.count(b"1=text 2=voice") >= 3
    assert b"evomag 244 lei" in sent
    assert b"for 244 lei, the" in sent  # the repeated answer (the request itself said something else)
    assert session.state == bridge.IDLE
    assert port.input_flushed >= 3


# --- ask_server keeps the result for those buttons --------------------------------


class FakeClient:
    results = {}

    def __init__(self, url, auth=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, args):
        data = {
            "start_errand": {"errand_id": "abc", "status": "running"},
            "get_status": {"status": "done", "progress": {"evomag": "ok"}},
            "get_result": FakeClient.results,
        }[name]
        return SimpleNamespace(data=data)


from types import SimpleNamespace  # noqa: E402


def _ask(monkeypatch, result, memory):
    import asyncio

    monkeypatch.setattr(bridge, "Client", FakeClient)
    monkeypatch.setattr(bridge, "POLL_SECONDS", 0)
    FakeClient.results = result
    return asyncio.run(bridge.ask_server("cheapest tv", "http://x/mcp", "tok", FakeDisplay(), memory))


def test_ask_server_remembers_a_finished_result(monkeypatch):
    memory = bridge.LastAnswer()
    assert _ask(monkeypatch, SAMPLE_RESULT, memory) == SAMPLE_RESULT["spoken_summary"]
    assert memory.summary == SAMPLE_RESULT["spoken_summary"]
    assert memory.shops[0] == "evomag 244 lei"


def test_a_new_request_forgets_the_old_answer_even_if_it_fails(monkeypatch):
    memory = bridge.LastAnswer()
    memory.remember(SAMPLE_RESULT)
    failed = {"status": "failed", "spoken_summary": "Sorry, I could not finish that errand."}
    assert _ask(monkeypatch, failed, memory) == failed["spoken_summary"]
    assert memory.summary is None


def test_a_request_that_times_out_leaves_nothing_to_repeat(monkeypatch):
    memory = bridge.LastAnswer()
    memory.remember(SAMPLE_RESULT)
    monkeypatch.setattr(bridge, "GIVE_UP_AFTER", 0)
    summary = _ask(monkeypatch, SAMPLE_RESULT, memory)
    assert summary == "Took too long. Please try again."
    assert memory.summary is None
    assert memory.shops == []


# --- reading answers aloud --------------------------------------------------------


class FakeSpeaker:
    def __init__(self):
        self.said = []
        self.stops = 0

    def say(self, text):
        self.said.append(text)

    def stop(self):
        self.stops += 1


def test_shop_phrases_have_no_length_limit_and_read_naturally():
    assert bridge.shop_phrase({"site_id": "evomag", "offers": [{"price": 244.0, "currency": "RON"}]}) == "evomag, 244 lei"
    assert bridge.shop_phrase({"site_id": "mediagalaxy", "offers": [{"price": 12499.5, "currency": "RON"}]}) == "mediagalaxy, 12500 lei"
    assert bridge.shop_phrase({"site_id": "vexio", "offers": [{"price": 80, "currency": "EUR"}]}) == "vexio, 80 EUR"
    assert bridge.shop_phrase({"site_id": "vexio", "status": "empty", "offers": []}) == "vexio, no matching offer"
    assert bridge.shop_phrase({"site_id": "altex", "status": "blocked"}) == "altex, blocked"


def test_spoken_details_are_cheapest_first():
    assert bridge.spoken_details(SAMPLE_RESULT["sites"]) == (
        "evomag, 244 lei. altex, 260 lei. mediagalaxy, 2499 lei. vexio, no matching offer."
    )


def test_the_answer_is_read_aloud_when_it_arrives(monkeypatch):
    speaker = FakeSpeaker()
    _run_serve(
        monkeypatch,
        lambda ui: ["ASK:1\n", lambda: ui.feed("cheapest tv"), "ASK:1\n"],
        answer="Evomag has it for 244 lei.",
        speaker=speaker,
    )
    assert speaker.said == ["Evomag has it for 244 lei."]


def test_a_failure_message_is_read_aloud_too(monkeypatch):
    async def boom(request, url, token, display, memory=None):
        raise ConnectionError("down")

    monkeypatch.setattr(bridge, "ask_server", boom)
    monkeypatch.setattr(bridge, "PAGE_SECONDS", 0)
    ui = RecordingUi()
    speaker = FakeSpeaker()
    port = ScriptedPort(["ASK:1\n", lambda: ui.feed("cheapest tv"), "ASK:1\n"])
    session = bridge.Session(bridge.Display(port), ui, None, sleep=lambda _s: None, speaker=speaker)
    with pytest.raises(KeyboardInterrupt):
        bridge.serve(port, "http://x/mcp", "tok", ui, None, session=session)
    assert speaker.said == ["Server error. Check the PC."]


def test_every_button_press_cuts_the_voice_first():
    speaker = FakeSpeaker()
    session = bridge.Session(FakeDisplay(), RecordingUi(), FakeVoice(), sleep=lambda _s: None, speaker=speaker)
    for button in ("1", "9"):
        before = speaker.stops
        session.press(button)
        assert speaker.stops == before + 1


def test_the_voice_is_cut_before_the_microphone_opens():
    order = []

    class Speaker(FakeSpeaker):
        def stop(self):
            order.append("voice stopped")

    class Voice(FakeVoice):
        def start(self):
            order.append("microphone opened")

    session = bridge.Session(FakeDisplay(), RecordingUi(), Voice(), sleep=lambda _s: None, speaker=Speaker())
    session.press("2")
    assert order == ["voice stopped", "microphone opened"]


def test_button_3_reads_the_last_answer_again():
    speaker = FakeSpeaker()
    session = bridge.Session(FakeDisplay(), RecordingUi(), None, sleep=lambda _s: None,
                             page_seconds=0, speaker=speaker)
    session.memory.remember(SAMPLE_RESULT)
    session.press("3")
    assert speaker.said == [SAMPLE_RESULT["spoken_summary"]]


def test_button_4_reads_the_shops_aloud():
    speaker = FakeSpeaker()
    session = bridge.Session(FakeDisplay(), RecordingUi(), None, sleep=lambda _s: None,
                             page_seconds=0, speaker=speaker)
    session.memory.remember(SAMPLE_RESULT)
    session.press("4")
    assert speaker.said == ["evomag, 244 lei. altex, 260 lei. mediagalaxy, 2499 lei. vexio, no matching offer."]


def test_nothing_is_read_when_there_is_nothing_to_repeat():
    speaker = FakeSpeaker()
    session = bridge.Session(FakeDisplay(), RecordingUi(), None, sleep=lambda _s: None, speaker=speaker)
    session.press("3")
    session.press("4")
    assert speaker.said == []


def test_make_speaker_returns_none_when_the_computer_has_no_voice(monkeypatch, capsys):
    import types

    module = types.ModuleType("speech_output")

    class Speaker:
        available = False

    module.Speaker = Speaker
    monkeypatch.setitem(sys.modules, "speech_output", module)
    assert bridge.make_speaker() is None
    assert "will not be read aloud" in capsys.readouterr().out


def test_make_speaker_returns_the_speaker_when_there_is_a_voice(monkeypatch):
    import types

    module = types.ModuleType("speech_output")

    class Speaker:
        available = True

    module.Speaker = Speaker
    monkeypatch.setitem(sys.modules, "speech_output", module)
    assert isinstance(bridge.make_speaker(), Speaker)

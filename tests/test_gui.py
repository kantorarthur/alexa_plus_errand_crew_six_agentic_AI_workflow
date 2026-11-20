"""The window: what it says in each situation, and that it works across threads."""

import importlib.util
import sys
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gui.py"
spec = importlib.util.spec_from_file_location("uno_gui", SCRIPT)
gui = importlib.util.module_from_spec(spec)
sys.modules["uno_gui"] = gui  # dataclasses looks the module up by name
spec.loader.exec_module(gui)


def test_typing_screen_has_an_editable_box_and_names_button_1():
    screen = gui.screen_for(gui.TYPING)
    assert screen.editable
    assert "button 1" in screen.hint


def test_listening_screen_says_listening_and_names_button_2():
    screen = gui.screen_for(gui.LISTENING)
    assert screen.headline == "Listening..."
    assert "button 2" in screen.hint
    assert not screen.editable


def test_transcribing_screen():
    assert gui.screen_for(gui.TRANSCRIBING).headline == "Transcribing..."


def test_heard_screen_shows_the_text_and_never_lets_it_be_edited():
    screen = gui.screen_for(gui.HEARD, "cheapest samsung tv", "Searching... 1/4 shops 3s")
    assert screen.body == "cheapest samsung tv"
    assert screen.hint == "Searching... 1/4 shops 3s"
    assert not screen.editable


def test_heard_nothing_is_stated_plainly():
    assert gui.screen_for(gui.HEARD, "").body == "(nothing)"


def test_searching_screen_shows_the_request():
    screen = gui.screen_for(gui.SEARCHING, "cheapest laptop")
    assert screen.headline == "Searching..."
    assert screen.body == "cheapest laptop"


def test_an_unknown_mode_is_an_error():
    with pytest.raises(ValueError):
        gui.screen_for("nonsense")


def _window():
    pytest.importorskip("tkinter")
    try:
        return gui.TkUi()
    except Exception as exc:  # no screen on this machine (for example a build server)
        pytest.skip(f"no screen: {exc}")


def test_the_window_works_across_threads():
    ui = _window()
    result = {}

    def serial_thread():
        ui.typing_started()
        ui._call(lambda: ui._text.insert("1.0", "cheapest   samsung\ntv"))
        result["typed"] = ui.get_typed_text()
        result["mode_after_send"] = ui._call(lambda: ui._mode)
        ui.status("Searching...", "2/4 shops 6s")
        result["hint"] = ui._call(lambda: ui._hint.cget("text"))
        ui.answered("done")
        result["visible"] = ui._call(lambda: ui._root.state())
        ui.quit()

    threading.Thread(target=serial_thread, daemon=True).start()
    ui.run()
    assert " ".join(result["typed"].split()) == "cheapest samsung tv"
    assert result["mode_after_send"] == gui.SEARCHING
    assert result["hint"] == "Searching... 2/4 shops 6s"
    assert result["visible"] == "withdrawn"


def test_status_is_ignored_when_the_window_is_not_showing_a_request():
    ui = _window()
    result = {}

    def serial_thread():
        ui.listening_started()
        ui.status("Listening...", "2 = stop")
        result["hint"] = ui._call(lambda: ui._hint.cget("text"))
        ui.quit()

    threading.Thread(target=serial_thread, daemon=True).start()
    ui.run()
    assert result["hint"] == gui.screen_for(gui.LISTENING).hint

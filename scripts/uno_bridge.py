"""Bridge between an Arduino Uno and the Errand Crew MCP server.

The Uno cannot do HTTPS, so it talks to this script over the USB serial cable and this
script talks to the server. Two buttons start a request:

  button 1  text input   type the request on the PC, press button 1 again to send it
  button 2  voice input  speak to the PC microphone, press button 2 again to stop,
                         the speech is turned into text and the request is sent

  button 3  repeat       shows the last answer again on the LCD
  button 4  details      shows the cheapest price of each shop for the last request,
                         two shops per screen, for example "evomag 244 lei"

Every answer is also read aloud through the PC's speakers (any button stops it); use
--no-speech to turn that off.

A small window opens on the PC while you type or speak
(python scripts/uno_bridge.py --no-window types in the terminal instead). The answer comes back
to the Uno's 16x2 LCD, two lines at a time, and the window closes.

Messages on the serial cable (one per line, plain ASCII):
  Uno -> PC   ASK:<button 1-4>         a button was pressed
  PC  -> Uno  D:<16 chars><16 chars>   what to show on LCD row 1 and row 2
  PC  -> Uno  R                        ready: the errand is over

  $env:MCP_TOKEN = "<one of the server's client tokens>"
  python scripts/uno_bridge.py --port COM3 --url https://<your-service>.onrender.com/mcp

Close the Arduino IDE's Serial Monitor first: only one program can hold the serial port.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import textwrap
import threading
import time
import unicodedata
from collections.abc import Awaitable, Callable

from fastmcp import Client
from fastmcp.exceptions import ToolError

BAUD = 9600
LCD_WIDTH = 16
PAGE_SECONDS = 3.0
POLL_SECONDS = 2
GIVE_UP_AFTER = 180
MIN_REQUEST_CHARS = 3  # the server refuses shorter requests
MAX_REQUEST_CHARS = 300
CAPTURE_TIMEOUT = 60  # seconds to type or to speak before giving up
MESSAGE_SECONDS = 2.0
FINISHED = {"ok", "empty", "blocked", "error"}

TEXT_BUTTON = "1"
VOICE_BUTTON = "2"
REPEAT_BUTTON = "3"
DETAILS_BUTTON = "4"

IDLE = "idle"
TYPING = "typing"
LISTENING = "listening"
PROCESSING = "processing"


def to_ascii(text: str) -> str:
    """The LCD only shows plain ASCII: drop accents and anything unprintable."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.split())


def pages(text: str) -> list[tuple[str, str]]:
    """Cut text into screens of two lines of at most LCD_WIDTH characters."""
    lines = textwrap.wrap(to_ascii(text), width=LCD_WIDTH, break_long_words=True)
    if not lines:
        return [("", "")]
    if len(lines) % 2:
        lines.append("")
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines), 2)]


def frame(top: str, bottom: str) -> bytes:
    """One screen as a serial line: 'D:' + row 1 + row 2, each padded to LCD_WIDTH."""
    top = to_ascii(top).ljust(LCD_WIDTH)[:LCD_WIDTH]
    bottom = to_ascii(bottom).ljust(LCD_WIDTH)[:LCD_WIDTH]
    return f"D:{top}{bottom}\n".encode("ascii")


class Display:
    """Talks to the Uno through anything with a write() method (a serial port)."""

    def __init__(self, port) -> None:
        self._port = port

    def show(self, top: str, bottom: str = "") -> None:
        self._port.write(frame(top, bottom))

    def ready(self) -> None:
        self._port.write(b"R\n")


CURRENCY_WORDS = {"RON": "lei"}
NO_OFFER_WORDS = {"empty": "none", "blocked": "blocked", "error": "error"}


def shop_line(site: dict) -> str:
    """One shop on one LCD row, at most 16 characters: 'evomag 244 lei'."""
    name = to_ascii(str(site.get("site_id", "?"))).lower() or "?"
    offers = site.get("offers") or []
    if offers:
        price = f"{round(offers[0]['price'])}"
        currency = CURRENCY_WORDS.get(offers[0].get("currency", "RON"), offers[0].get("currency", ""))
        for tail in (f" {price} {currency}".rstrip(), f" {price}"):
            if len(name) + len(tail) <= LCD_WIDTH:
                return name + tail
        return name[: max(1, LCD_WIDTH - len(price) - 1)] + f" {price}"
    word = NO_OFFER_WORDS.get(site.get("status", ""), "none")
    tail = f" {word}"
    return name[: max(1, LCD_WIDTH - len(tail))] + tail


def shop_lines(sites: list[dict]) -> list[str]:
    """Cheapest shops first, then the shops that had nothing to show."""
    ordered = sorted(
        sites,
        key=lambda site: (0, site["offers"][0]["price"]) if site.get("offers") else (1, 0),
    )
    return [shop_line(site) for site in ordered]


def shop_phrase(site: dict) -> str:
    """One shop as a spoken phrase, with no 16-character limit: 'evomag, 244 lei'."""
    name = str(site.get("site_id", "a shop"))
    offers = site.get("offers") or []
    if offers:
        currency = CURRENCY_WORDS.get(offers[0].get("currency", "RON"), offers[0].get("currency", ""))
        return f"{name}, {round(offers[0]['price'])} {currency}".rstrip()
    words = {"empty": "no matching offer", "blocked": "blocked", "error": "error"}
    return f"{name}, {words.get(site.get('status', ''), 'no offer')}"


def spoken_details(sites: list[dict]) -> str:
    """The details button, said aloud: cheapest shop first, one sentence per shop."""
    ordered = sorted(
        sites,
        key=lambda site: (0, site["offers"][0]["price"]) if site.get("offers") else (1, 0),
    )
    return " ".join(shop_phrase(site) + "." for site in ordered)


class LastAnswer:
    """The last finished answer, kept for the repeat and details buttons."""

    def __init__(self) -> None:
        self.summary: str | None = None
        self.shops: list[str] = []
        self.spoken_shops = ""

    def clear(self) -> None:
        self.summary = None
        self.shops = []
        self.spoken_shops = ""

    def remember(self, result: dict) -> None:
        """Keep a finished result. A failed one is not kept: there is nothing to repeat."""
        self.clear()
        if result.get("status") == "done" and result.get("spoken_summary"):
            self.summary = result["spoken_summary"]
            self.shops = shop_lines(result.get("sites") or [])
            self.spoken_shops = spoken_details(result.get("sites") or [])


async def ask_server(request: str, url: str, token: str, display: Display, memory=None) -> str:
    """Start an errand, show progress on the LCD, and return the spoken summary.

    The finished result is kept in memory (if given) for buttons 3 and 4."""
    if memory is not None:
        memory.clear()  # a new request replaces the old answer, even if this one fails
    started = time.time()
    async with Client(url, auth=token) as client:
        start = (await client.call_tool("start_errand", {"request": request})).data
        errand_id = start["errand_id"]
        while time.time() - started < GIVE_UP_AFTER:
            status = (await client.call_tool("get_status", {"errand_id": errand_id})).data
            progress = status.get("progress") or {}
            done = sum(1 for state in progress.values() if state in FINISHED)
            display.show("Searching...", f"{done}/{len(progress) or '?'} shops {int(time.time() - started)}s")
            if status["status"] in ("done", "failed"):
                break
            await asyncio.sleep(POLL_SECONDS)
        else:
            return "Took too long. Please try again."
        result = (await client.call_tool("get_result", {"errand_id": errand_id})).data
    if memory is not None:
        memory.remember(result)
    return result["spoken_summary"]


async def handle_request(
    display: Display,
    request: str,
    ask: Callable[[str], Awaitable[str]],
    page_seconds: float | None = None,
    on_answer: Callable[[str], None] | None = None,
) -> None:
    """Run one request end to end. Always ends by telling the Uno it is ready again."""
    page_seconds = PAGE_SECONDS if page_seconds is None else page_seconds
    display.show("Asking...", request)
    try:
        summary = await ask(request)
    except ToolError as exc:
        print("Server refused:", exc)
        summary = str(exc)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not talk to the server ({type(exc).__name__}).")
        summary = "Server error. Check the PC."
    print("Answer:", summary)
    if on_answer is not None:
        on_answer(summary)
    for top, bottom in pages(summary):
        display.show(top, bottom)
        await asyncio.sleep(page_seconds)
    display.ready()


class TeeDisplay:
    """Everything shown on the LCD is also given to the window, as a status line."""

    def __init__(self, display, ui) -> None:
        self._display = display
        self._ui = ui

    def show(self, top: str, bottom: str = "") -> None:
        self._display.show(top, bottom)
        self._ui.status(top, bottom)

    def ready(self) -> None:
        self._display.ready()


class Session:
    """What the buttons mean right now.

    idle -> (button 1) typing -> (button 1) processing
    idle -> (button 2) listening -> (button 2) processing
    Any other press is ignored. Nothing here touches the network or the microphone:
    the screen, the voice recorder and the typing box are passed in, so it can be tested.
    """

    def __init__(self, display, ui, voice=None, clock=time.monotonic, sleep=time.sleep,
                 timeout: float = CAPTURE_TIMEOUT, message_seconds: float = MESSAGE_SECONDS,
                 page_seconds: float | None = None, memory: LastAnswer | None = None,
                 flush: Callable[[], None] | None = None, speaker=None) -> None:
        self.display = display
        self.speaker = speaker
        self.ui = ui
        self.voice = voice
        self.memory = memory if memory is not None else LastAnswer()
        self._flush = flush
        self._page_seconds = page_seconds
        self.state = IDLE
        self._clock = clock
        self._sleep = sleep
        self._timeout = timeout
        self._message_seconds = message_seconds
        self._started_at = 0.0

    def start(self) -> None:
        self.display.show("1=text 2=voice", "3=repeat 4=more")

    def press(self, button: str) -> str | None:
        """Handle a button press. Returns the request to send, or None."""
        if self.speaker is not None:
            self.speaker.stop()  # any button cuts the voice, and the microphone must not hear it
        if self.state == IDLE:
            if button == TEXT_BUTTON:
                self._begin(TYPING)
                self.display.show("Type on PC...", "1 = send")
                self.ui.typing_started()
            elif button == VOICE_BUTTON:
                self._begin_listening()
            elif button == REPEAT_BUTTON:
                self._repeat()
            elif button == DETAILS_BUTTON:
                self._details()
            return None
        if self.state == TYPING and button == TEXT_BUTTON:
            return self._submit(self.ui.get_typed_text(), heard=False)
        if self.state == LISTENING and button == VOICE_BUTTON:
            return self._submit(self._transcribe(), heard=True)
        return None

    def tick(self) -> None:
        """Called about once a second: stops a typing or listening that was forgotten."""
        if self.state not in (TYPING, LISTENING):
            return
        if self._clock() - self._started_at < self._timeout:
            return
        if self.state == LISTENING and self.voice is not None:
            self.voice.cancel()
        self._back_to_idle("Timeout", "Try again")

    def finish(self) -> None:
        """The request is over (answer shown, or it failed)."""
        self.state = IDLE
        # Presses made while the screen was busy were queued by the cable: drop them.
        if self._flush is not None:
            self._flush()
        self.start()

    def _repeat(self) -> None:
        summary = self.memory.summary
        if not summary:
            self._note("Nothing to", "repeat yet")
            return
        print(f'\nRepeating: "{summary}"')
        self._say(summary)
        self._play(pages(summary))

    def _details(self) -> None:
        lines = self.memory.shops
        if not lines:
            self._note("No details yet", "Ask first")
            return
        print("\nDetails:\n" + "\n".join(f"  {line}" for line in lines))
        self._say(self.memory.spoken_shops)
        self._play([(lines[i], lines[i + 1] if i + 1 < len(lines) else "") for i in range(0, len(lines), 2)])

    def _say(self, text: str) -> None:
        if self.speaker is not None:
            self.speaker.say(text)

    def _play(self, screens: list[tuple[str, str]]) -> None:
        pause = PAGE_SECONDS if self._page_seconds is None else self._page_seconds
        for top, bottom in screens:
            self.display.show(top, bottom)
            self._sleep(pause)
        self.finish()

    def _note(self, top: str, bottom: str) -> None:
        self.display.show(top, bottom)
        self._sleep(self._message_seconds)
        self.finish()

    def _begin(self, state: str) -> None:
        self.state = state
        self._started_at = self._clock()

    def _begin_listening(self) -> None:
        if self.voice is None:
            self._back_to_idle("No voice input", "Not installed")
            return
        try:
            self.voice.start()
        except Exception as exc:  # noqa: BLE001
            print(f"Could not start the microphone ({type(exc).__name__}: {exc}).")
            self._back_to_idle("Mic error", "Check the PC")
            return
        self._begin(LISTENING)
        self.display.show("Listening...", "2 = stop")
        self.ui.listening_started()

    def _transcribe(self) -> str:
        self.state = PROCESSING
        self.display.show("Transcribing...", "")
        self.ui.transcribing()
        try:
            return self.voice.stop()
        except Exception as exc:  # noqa: BLE001
            print(f"Could not turn speech into text ({type(exc).__name__}: {exc}).")
            return ""

    def _submit(self, text: str, heard: bool) -> str | None:
        text = " ".join(text.split())[:MAX_REQUEST_CHARS]
        if heard:
            self.ui.heard(text)
        if len(text) < MIN_REQUEST_CHARS:
            self._back_to_idle("Not understood", "Try again")
            return None
        self.state = PROCESSING
        if heard:
            self.display.show("Heard:", text)
        return text

    def _back_to_idle(self, top: str, bottom: str) -> None:
        self.state = IDLE
        self.ui.cancelled(top)
        self.display.show(top, bottom)
        self._sleep(self._message_seconds)
        self.display.ready()
        self.start()


class ConsoleUi:
    """Used without a window (--no-window): typing happens in this terminal. Lines typed
    while a request is being typed are joined with spaces, and button 1 sends them."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._active = False
        self._lock = threading.Lock()

    def feed(self, line: str) -> None:
        with self._lock:
            if self._active and line.strip():
                self._lines.append(line.strip())

    def typing_started(self) -> None:
        with self._lock:
            self._lines = []
            self._active = True
        print("\nType your request here, then press button 1 on the Uno to send it.")

    def get_typed_text(self) -> str:
        with self._lock:
            self._active = False
            text = " ".join(self._lines)
            self._lines = []
        return text

    def listening_started(self) -> None:
        print("\nListening... press button 2 on the Uno to stop.")

    def transcribing(self) -> None:
        print("Transcribing...")

    def heard(self, text: str) -> None:
        print(f'Heard: "{text}"' if text else "Heard nothing.")

    def status(self, top: str, bottom: str) -> None:
        pass

    def answered(self, summary: str) -> None:
        pass

    def cancelled(self, reason: str) -> None:
        with self._lock:
            self._active = False
            self._lines = []
        print(f"\n{reason}.")


def keyboard_loop(ui: ConsoleUi) -> None:
    while True:
        try:
            line = input()
        except EOFError:
            return
        ui.feed(line)


def parse_press(line: str) -> str | None:
    """'ASK:1' -> '1'. Anything else is not a button press."""
    line = line.strip()
    if not line.startswith("ASK:"):
        return None
    button = line[4:].strip()
    return button if button in ("1", "2", "3", "4") else None


def serve(port, url: str, token: str, ui, voice=None, session: Session | None = None,
          speaker=None) -> None:
    display = TeeDisplay(Display(port), ui)
    session = session or Session(display, ui, voice, speaker=speaker,
                                 flush=getattr(port, "reset_input_buffer", None))
    session.start()
    while True:
        line = port.readline().decode("ascii", errors="ignore")
        button = parse_press(line)
        if button is None:
            session.tick()
            continue
        request = session.press(button)
        if request is None:
            continue
        print(f'\nAsking the server: "{request}"')

        async def ask(text: str) -> str:
            return await ask_server(text, url, token, display, session.memory)

        def on_answer(summary: str) -> None:
            ui.answered(summary)
            session._say(summary)

        asyncio.run(handle_request(display, request, ask, on_answer=on_answer))
        session.finish()


def make_voice():
    """The speech-to-text recorder, or None when its packages are not installed."""
    try:
        import voice as voice_module  # noqa: PLC0415
    except ImportError:
        return None
    missing = voice_module.missing_packages()
    if missing:
        print("Voice input needs:  pip install " + " ".join(missing))
        return None
    voice = voice_module.Voice()

    def warm_up() -> None:
        print("Loading the speech model (the first time it is downloaded)...")
        try:
            voice.warm_up()
        except Exception as exc:  # noqa: BLE001
            print(f"Could not load the speech model ({type(exc).__name__}): {exc}")
            return
        print("Speech model ready.")

    threading.Thread(target=warm_up, daemon=True).start()
    return voice


def make_speaker():
    """The text-to-speech output, or None when this computer has no voice program."""
    try:
        import speech_output  # noqa: PLC0415
    except ImportError:
        return None
    speaker = speech_output.Speaker()
    if not speaker.available:
        print("No voice program found on this computer: answers will not be read aloud.")
        return None
    return speaker


def make_ui(use_window: bool):
    """The window if there is one, otherwise typing in this terminal."""
    if use_window:
        try:
            from gui import TkUi  # noqa: PLC0415

            return TkUi()
        except Exception as exc:  # noqa: BLE001  (no tkinter, or no screen)
            print(f"No window available ({type(exc).__name__}): typing in this terminal instead.")
    ui = ConsoleUi()
    threading.Thread(target=keyboard_loop, args=(ui,), daemon=True).start()
    return ui


def run_serial(port_name: str, url: str, token: str, ui, voice, speaker=None) -> None:
    import serial  # imported here so the helpers above work without pyserial

    with serial.Serial(port_name, BAUD, timeout=1) as port:
        time.sleep(2)  # opening the port resets the Uno; give it time to boot
        serve(port, url, token, ui, voice, speaker=speaker)


def main() -> int:
    parser = argparse.ArgumentParser(description="Arduino Uno bridge for Errand Crew")
    parser.add_argument("--port", required=True, help="serial port, e.g. COM3 or /dev/ttyACM0")
    parser.add_argument("--url", default=os.environ.get("MCP_URL", "http://localhost:8000/mcp"))
    parser.add_argument("--no-window", action="store_true", help="type in the terminal, no window")
    parser.add_argument("--no-speech", action="store_true", help="do not read answers aloud")
    args = parser.parse_args()
    token = os.environ.get("MCP_TOKEN", "")
    if not token:
        print("Set MCP_TOKEN in this terminal first (one of the server's client tokens).")
        return 2

    ui = make_ui(not args.no_window)
    voice = make_voice()
    speaker = None if args.no_speech else make_speaker()
    if voice is None:
        print("Voice input is not available: button 2 will say so.")

    if not hasattr(ui, "run"):  # terminal mode: the serial loop runs right here
        print("Button 1: type a request here, press button 1 again to send.")
        try:
            run_serial(args.port, args.url, token, ui, voice, speaker)
        except KeyboardInterrupt:
            return 130
        return 0

    # Window mode: the window must own the main thread, so the serial loop runs beside it.
    outcome = {"code": 0}

    def worker() -> None:
        try:
            run_serial(args.port, args.url, token, ui, voice, speaker)
        except Exception as exc:  # noqa: BLE001
            print(f"Stopped: {exc}")
            outcome["code"] = 1
        finally:
            ui.quit()

    threading.Thread(target=worker, daemon=True).start()
    print("Window mode: press button 1 or 2 on the Uno. Ctrl+C here to stop.")
    try:
        ui.run()
    except KeyboardInterrupt:
        return 130
    return outcome["code"]


if __name__ == "__main__":
    raise SystemExit(main())

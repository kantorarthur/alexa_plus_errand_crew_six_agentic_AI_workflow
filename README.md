<img width="1280" height="640" alt="Image" src="https://github.com/user-attachments/assets/8131660f-ae9d-42e0-a7b6-bf20ac929355" />

# Errand Crew - an observable six agentic AI workflow

### Speak a product request, and six AI agents compare prices across Romanian shops in parallel and read the cheapest offer back to you.

The initial project was developed in 7 hours during the Amazon Developer Hackaton! (https://devpost.com/software/errand-crew)

## Live Demo - Speak your request and get back the answer in less than a minute!
https://github.com/user-attachments/assets/d5f4bf88-2ab3-4244-97a6-8416f87bfa19

### The MCP server uses a six agentic AI workflow

- **A planner** (Claude Sonnet 5.5) turns the spoken request into a plan.
- **Four worker agents** (Claude Haiku 5.5) browse Evomag, Altex, MediaGalaxy and Vexio in parallel, each in its own cloud browser.
- **The judge** picks the cheapest match in code. A model (Claude Haiku 5.5) only words the result for speech, so the spoken answer never depends on a model behaving.

**You can watch the agents work.** The browsers run on the [Kernel](https://www.kernel.sh) cloud browser infrastructure, as shown in the demo video below. If you run the server yourself with your own Kernel key and `KERNEL_HEADLESS=false`, you can see the four browsers live in the Kernel dashboard.



<img width="2000" height="1120" alt="Image" src="https://github.com/user-attachments/assets/c98256af-f620-46ad-b8e3-2c8ffc7c06a3" />



## Contents

- [How it works](#how-it-works)
- [The Arduino Uno desk gadget](#the-arduino-uno-desk-gadget)
- [Build and run](#build-and-run)
- [Dependencies](#dependencies)
- [Technical overview](#technical-overview)
- [Problems I encountered](#problems-i-encountered)
- [Security model](#security-model-prompt-injection-and-ai-hallucinations)

## How it works

1. You ask for a product: by voice or text through an MCP client (a voice assistant, or the demo client), or on the Arduino gadget.
2. The **planner** (Claude Sonnet 5.5) turns the request into a shop category and a short list of shops.
3. Up to four **workers** (Claude Haiku 5.5) each drive a cloud browser on one shop, in parallel, and read the product listing.
4. The **judge** picks the cheapest matching offer in plain code. A model only puts the result into words.
5. You get a short spoken answer. On the gadget it also appears on the LCD, and the PC's speakers read it aloud.

The server only reads public shop pages. It never logs in, buys or submits anything.

## The Arduino Uno desk gadget

An Arduino Uno cannot reach the internet and has 2 KB of memory, so it does not run the agents. It is the control panel. A PC runs a small bridge script that talks to the Uno over the USB cable and to the Errand Crew server over the network. The PC also does the speech: it turns your voice into text with an open speech model (Whisper, running on your own computer, nothing is sent to a cloud service) and reads the answer aloud through the PC's speakers.

```
 Uno (buttons + 16x2 LCD)        PC                              Errand Crew server
 ------------------------   USB  ----------------------   HTTPS  ------------------
  button pressed  ------------>  scripts/uno_bridge.py  ------------>  MCP tools
  LCD shows text  <------------   + window (type / listen)  <--------  start_errand
                                  + Whisper (speech to text)          get_status
                                  + PC voice (text to speech)         get_result
```

### The four buttons

| Button | What it does |
|---|---|
| **1 - text** | A window opens. Type your request and press button 1 again to send it. |
| **2 - voice** | The window says "Listening...". Speak, then press button 2 again. The speech is turned into text, the window shows what was heard, and the request is sent. |
| **3 - repeat** | Shows (and reads aloud) the last answer again. |
| **4 - details** | Shows the cheapest price of every shop, two shops per LCD screen, for example `evomag 244 lei`, and reads them aloud. |

While an errand is running the LCD shows progress such as `2/4 shops 12s`. When the answer arrives it is shown two lines at a time, read aloud, and the window closes. Pressing any button stops the voice. If you forget to press the second time, typing or listening stops by itself after 60 seconds.

### What you need

| Part | Notes |
|---|---|
| Arduino Uno (R3, or a clone with a CH340 chip) | USB cable with data lines (some cables only charge) |
| 16x2 LCD with an I2C backpack | Usually address `0x27`, sometimes `0x3F` |
| 4 tactile push buttons | 4-leg buttons, plus a breadboard and jumper wires |
| A PC with a microphone and speakers | Laptop microphone and speakers are fine, or USB ones |

### Wiring

| LCD (I2C) | Uno |
|---|---|
| GND | GND |
| VCC | 5V |
| SDA | A4 |
| SCL | A5 |

| Button | Uno pin | Other leg |
|---|---|---|
| 1 | D2 | GND |
| 2 | D3 | GND |
| 3 | D4 | GND |
| 4 | D5 | GND |

No resistors are needed: the sketch uses the Uno's built-in pull-up resistors (`INPUT_PULLUP`), so a button reads as pressed when it connects its pin to GND.

Tips from building it:

- Put each button across the center channel of the breadboard. Wire the pin to a leg on one side and GND to the **diagonally opposite** leg on the other side. On a 4-leg button, two neighbouring legs may be connected inside, so wiring the diagonal ones guarantees the button only connects when pressed. If a button looks pressed all the time, this is the first thing to check.
- Use a short wire to GND and keep the pin wires firmly seated. A loose wire makes a pin pick up noise.
- If the LCD stays blank, turn the contrast screw on the I2C backpack, and try the address `0x3F` instead of `0x27` in `hardware/uno_errand/uno_errand.ino`.

### The serial protocol

One line per message, 9600 baud, plain ASCII. The Uno only reports presses, so the PC decides what every button means.

| Direction | Message | Meaning |
|---|---|---|
| Uno to PC | `ASK:<1-4>` | A button was pressed |
| PC to Uno | `D:<16 chars><16 chars>` | What to show on LCD row 1 and row 2 |
| PC to Uno | `R` | The errand is over |

### The files

| File | What it is |
|---|---|
| `hardware/uno_errand/uno_errand.ino` | The sketch for the Uno: reads the buttons, shows text on the LCD |
| `scripts/uno_bridge.py` | The bridge: button logic, serial port, MCP client, LCD paging |
| `scripts/gui.py` | The window for typing and listening (tkinter) |
| `scripts/voice.py` | Microphone recording and speech to text (Whisper through faster-whisper) |
| `scripts/speech_output.py` | Reads answers aloud with the operating system's own voice |
| `scripts/requirements-uno.txt` | Python packages for the gadget |
| `tests/test_uno_bridge.py`, `test_gui.py`, `test_voice.py`, `test_speech_output.py` | Tests, using a fake LCD, microphone and voice |

## Build and run

There are three parts. Part 1 installs the code and is always needed. Part 2 gives you a server (on Render or on your own computer), or you can use a server someone else runs. Part 3 is the Arduino gadget and is optional.

| You want to... | Do |
|---|---|
| Run your own server | Part 1, then Part 2 (Render or local). You need your own [Anthropic](https://console.anthropic.com) and [Kernel](https://www.kernel.sh) API keys. |
| Try someone else's server | Part 1, then the demo client in Part 2 with their URL and token. No API keys needed. |
| Use the Arduino gadget | Part 1, a running server (Part 2), then Part 3 |

### Part 1: Get the code and install it

Do this on every computer that runs the server, the demo client or the Arduino bridge, even if the server itself runs on Render: the demo client and the bridge are Python scripts that need these packages.

**Windows (PowerShell):**

```powershell
git clone https://github.com/kantorarthur/alexa_plus_errand_crew_six_agentic_AI_workflow.git
cd alexa_plus_errand_crew_six_agentic_AI_workflow
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -r scripts\requirements-uno.txt
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

**macOS and Linux:**

```bash
git clone https://github.com/kantorarthur/alexa_plus_errand_crew_six_agentic_AI_workflow.git
cd alexa_plus_errand_crew_six_agentic_AI_workflow
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r scripts/requirements-uno.txt
.venv/bin/python -m pip install -r requirements-dev.txt
```

Always use the `.venv` copy of Python as shown. On Linux, running `pip` outside the virtual environment fails with "externally-managed-environment", and `--break-system-packages` is not needed.

`requirements.txt` is the server and the demo client. `scripts/requirements-uno.txt` is only for the Arduino gadget (serial port, microphone, speech model). `requirements-dev.txt` is only for the tests. If you only want the server, `requirements.txt` is enough.

**Linux only: system packages** (the gadget needs them, they cannot come from pip):

```bash
sudo apt install python3-venv python3-tk libportaudio2 espeak-ng
sudo usermod -aG dialout $USER
```

`python3-tk` is for the window, `libportaudio2` for the microphone, `espeak-ng` for the voice. The `usermod` line lets your user open the Arduino's serial port; log out and back in afterwards. Windows needs none of this: tkinter comes with Python from python.org, and the voice comes with Windows.

### Part 2: A server

#### Environment variables

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Your Claude API key |
| `KERNEL_API_KEY` | Your Kernel API key |
| `ERRAND_CREW_TOKENS` | One bearer token per client, as `name:token,name:token`. Each token needs at least 24 characters and no commas, and all tokens must differ. Remove a pair to revoke that client. |
| `KERNEL_HEADLESS` | Optional. `false` (the default) opens browsers with a screen you can watch in the Kernel dashboard. `true` runs them headless, which is faster and cheaper. |

Generate a token with any random string tool, for example `openssl rand -hex 16`. Never put a real key or token in the repository or in a chat.

#### Option A: Deploy on Render

1. Fork or connect this repository in [Render](https://render.com) and create a **Web Service** from it.
2. Use these settings:

   | Setting | Value |
   |---|---|
   | Language | Python 3 (3.13) |
   | Branch | `main` |
   | Build command | `pip install -r requirements.txt` |
   | Start command | `PYTHONPATH=src python -m errand_crew.server` |
   | Health check path | `/health` |

3. Add the four environment variables above in the service's **Environment** settings. For a hosted demo we recommend `KERNEL_HEADLESS=true`.
4. Deploy. When the service shows **Live**, the MCP endpoint is `https://<your-service>.onrender.com/mcp`.

Render's free plan puts the service to sleep when idle, so the first request after a pause is slow. A paid instance avoids that. Render sets the allowed host name by itself.

Nothing else runs on your computer for the server. You still need Part 1 on the computer that runs the demo client or the Arduino bridge.

#### Option B: Run the server locally

macOS and Linux:

```bash
export ANTHROPIC_API_KEY="..."
export KERNEL_API_KEY="..."
export ERRAND_CREW_TOKENS="demo:<your-random-token>"
export PYTHONPATH=src
.venv/bin/python -m errand_crew.server
```

Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "..."
$env:KERNEL_API_KEY = "..."
$env:ERRAND_CREW_TOKENS = "demo:<your-random-token>"
$env:PYTHONPATH = "src"
.venv\Scripts\python -m errand_crew.server
```

The server listens on `http://localhost:8000`, with the MCP endpoint at `/mcp` and a health check at `/health`. Leave this terminal open and use a second terminal, opened in the project folder, for the next steps. Environment variables are per terminal, so set `MCP_TOKEN` again there.

#### Try it: the demo client

The demo client behaves like a voice assistant: it starts an errand, polls its status and prints the spoken summary and the Claude usage. Set `MCP_TOKEN` to one of the tokens from `ERRAND_CREW_TOKENS`, then run it with your request first and the server URL second.

macOS and Linux:

```bash
export MCP_TOKEN="<your-random-token>"
.venv/bin/python scripts/demo_client.py "cheapest 27 inch gaming monitor" http://localhost:8000/mcp
```

Windows PowerShell:

```powershell
$env:MCP_TOKEN = "<your-random-token>"
.venv\Scripts\python scripts\demo_client.py "cheapest 27 inch gaming monitor" http://localhost:8000/mcp
```

For a Render deployment, pass its URL instead: `https://<your-service>.onrender.com/mcp`.

#### Run the tests

macOS and Linux:

```bash
.venv/bin/python -m pytest -q
```

Windows PowerShell:

```powershell
.venv\Scripts\python -m pytest -q
```

The tests use a scripted model, a fake browser, a fake LCD, a fake microphone and a fake voice, so they need no network, no keys, no Arduino and cost nothing. Window tests need a screen and one optional test needs Chromium; they are skipped when those are not available.

### Part 3: The Arduino gadget

You need a running server (Part 2) and one of its client tokens.

**1. Wire it** as shown in [Wiring](#wiring).

**2. Put the sketch on the Uno (once).**

1. Install the [Arduino IDE](https://www.arduino.cc/en/software).
2. In the IDE open **Library Manager** and install **LiquidCrystal I2C** by Frank de Brabander.
3. Open `hardware/uno_errand/uno_errand.ino`, choose **Tools > Board > Arduino Uno** and your port under **Tools > Port**, then press **Upload**.
4. Close the IDE's **Serial Monitor**. Only one program can use the serial port, and the bridge needs it.

**3. Find the Uno's serial port.**

Windows PowerShell:

```powershell
.venv\Scripts\python -m serial.tools.list_ports
```

macOS and Linux:

```bash
.venv/bin/python -m serial.tools.list_ports
```

Look for a line that mentions `CH340`, `USB-SERIAL` or `Arduino`. The port is `COM3` or similar on Windows, `/dev/ttyUSB0` or `/dev/ttyACM0` on Linux and `/dev/cu.usbserial-...` on macOS. If the list is empty, check the USB cable (it must carry data) and, on Windows, the CH340 driver.

**4. Check the microphone and the voice** (optional, but it saves time). The first run of `voice.py --test` downloads the speech model, several hundred MB, and keeps it afterwards.

Windows PowerShell:

```powershell
.venv\Scripts\python scripts\voice.py --list
.venv\Scripts\python scripts\voice.py --test
.venv\Scripts\python scripts\speech_output.py "Evomag has it for 244 lei"
```

macOS and Linux:

```bash
.venv/bin/python scripts/voice.py --list
.venv/bin/python scripts/voice.py --test
.venv/bin/python scripts/speech_output.py "Evomag has it for 244 lei"
```

`--list` shows the microphones with their numbers. `--test` waits for Enter, records until you press Enter again, and prints what it heard. The last command reads a sentence aloud.

**5. Run the bridge.** Use the same terminal for both lines. Replace the port with the one from step 3, and the URL with your server's `/mcp` address.

Windows PowerShell:

```powershell
$env:MCP_TOKEN = "<one of the server's client tokens>"
.venv\Scripts\python scripts\uno_bridge.py --port COM3 --url https://<your-service>.onrender.com/mcp
```

macOS and Linux:

```bash
export MCP_TOKEN="<one of the server's client tokens>"
.venv/bin/python scripts/uno_bridge.py --port /dev/ttyUSB0 --url https://<your-service>.onrender.com/mcp
```

Against a server on the same computer, use `--url http://localhost:8000/mcp`. Wait for "Speech model ready." in the terminal, then press button 1 or 2 on the Uno. Stop the bridge with Ctrl+C.

#### Options and settings

| Option | Meaning |
|---|---|
| `--port` | Serial port of the Uno (required) |
| `--url` | The server's MCP address. Default: the `MCP_URL` environment variable, or `http://localhost:8000/mcp` |
| `--no-window` | No window: type your request in the terminal instead |
| `--no-speech` | Do not read answers aloud |

| Environment variable | Meaning |
|---|---|
| `MCP_TOKEN` | Required. One of the server's client tokens |
| `VOICE_MODEL` | `tiny`, `base`, `small` (default) or `medium`. Bigger is more exact and slower |
| `VOICE_LANGUAGE` | For example `ro` or `en`. Fixing the language avoids wrong guesses on short phrases. Default: detect |
| `VOICE_DEVICE` | The microphone's number from `voice.py --list`. Default: the system default |
| `SPEECH_RATE` | Speaking speed from `-10` (slow) to `10` (fast), Windows only. Default `0` |

To choose which speakers play the voice, set the sound output in the operating system (Windows: Settings > System > Sound > Output). On Linux a single program can be pointed at another output with `export PULSE_SINK="<sink name>"`, using a name from `pactl list short sinks`.

#### If something does not work

| Symptom | Likely cause |
|---|---|
| `could not open port` | Wrong port name, or the Serial Monitor (or another bridge) is using it. Close it and check `serial.tools.list_ports`. On Linux, check the `dialout` group. |
| `Set MCP_TOKEN in this terminal first` | The variable was set in a different terminal window |
| LCD is blank | Contrast screw on the I2C backpack, or the address is `0x3F` instead of `0x27` |
| A button looks pressed all the time | Button wired on neighbouring legs (use diagonal ones), or the wire is in pin 0 or 1 instead of 2 to 5 |
| Button 2 shows `No voice input` | Packages from `scripts/requirements-uno.txt` are missing |
| `No voice program found on this computer` | On Linux, install `espeak-ng`. Windows and macOS have a voice built in. |
| Window does not appear | tkinter is missing (Linux: `python3-tk`). The bridge falls back to typing in the terminal. |
| The answer is an error message | The server or its API key has a problem. Check the server's logs. |

## Dependencies

**Python:** 3.13 on Render (`PYTHON_VERSION=3.13.5`); the tests also run on 3.14. The tests of the Arduino scripts also pass on 3.12.

### Runtime (`requirements.txt`)

| Package | Version | What it is used for |
|---|---|---|
| `fastmcp` | 4.1.3 | MCP server over Streamable HTTP, bearer-token auth hook, MCP client in the demo script and the Arduino bridge |
| `anthropic` | 2.1.0 | Claude API client (planner, workers and judge wording) |
| `kernel` | 0.129.0 | Kernel SDK: creates and deletes the cloud browsers and runs Playwright code in them |
| `pydantic` | 2.14.1 | Validation of every data shape, including everything a model returns |
| `PyYAML` | 6.0.3 | Loads the shop registry (`sites.yaml`) |
| `uvicorn` | 0.54.0 | ASGI server that runs the app |

Standard library: `asyncio`, `hmac`, `statistics`, `contextvars`, `dataclasses`, `urllib`, `re`, `json`, `logging`.

### Arduino gadget (`scripts/requirements-uno.txt`)

| Package | What it is used for |
|---|---|
| `pyserial` | The USB serial connection to the Uno |
| `sounddevice` | Recording from the microphone (needs PortAudio: included in the Windows and macOS wheels, `libportaudio2` on Linux) |
| `numpy` | Audio buffers |
| `faster-whisper` (1.2 or newer) | Runs the Whisper speech model on the CPU, locally |

Also used: `tkinter` (standard library, for the window; on Linux the `python3-tk` system package), the Whisper `small` model (downloaded on first use), the operating system's own voice for reading answers (Windows `System.Speech` through PowerShell, macOS `say`, Linux `espeak-ng`), and on the Arduino side the **LiquidCrystal I2C** library.

### Development (`requirements-dev.txt`)

| Package | Version | Use |
|---|---|---|
| `pytest` | 9.1.1 | Test runner |
| `pytest-asyncio` | 1.4.0 | Async tests |
| `httpx` | 0.28.1 | Test client |

One test runs a real Chromium through `playwright` to check the price-decimal fix. It is optional and is skipped when Playwright or Chromium is not installed. The window tests need a screen and are skipped without one.

### External services

| Service | Role | Credential |
|---|---|---|
| Anthropic API | Claude Sonnet 5.5 (planner), Claude Haiku 5.5 (workers, judge wording) | `ANTHROPIC_API_KEY` |
| Kernel | Cloud browsers, one per shop | `KERNEL_API_KEY` |
| Render | Hosting for the MCP server | none in the code; secrets are set in its dashboard |

Clients authenticate to the server with a bearer token from `ERRAND_CREW_TOKENS`. Nothing else is needed: no database, no queue, no extra cloud service. Speech to text and text to speech run on your own computer.

## Technical overview

**Stack:** Python, [FastMCP](https://gofastmcp.com) (MCP over Streamable HTTP), the Anthropic API (Claude Sonnet 5.5 and Claude Haiku 5.5), Kernel.sh API, deployed on Render. The desk gadget adds an Arduino Uno (C++ sketch), pyserial, tkinter, faster-whisper (Whisper) and the operating system's voice.

## MCP tools (the interface)

Defined in [`src/errand_crew/server.py`](src/errand_crew/server.py), served at `/mcp` over Streamable HTTP. Every call needs `Authorization: Bearer <token>`. All three tools are marked read-only: they never log in, buy or submit anything.

A voice assistant should call `start_errand`, poll `get_status` every few seconds, then read `spoken_summary` from `get_result`. The Arduino bridge does exactly this.

### `start_errand(request)`

Starts comparing prices in the background and returns at once.

| Input | Type | Rules |
|---|---|---|
| `request` | string | 3 to 300 characters, for example `"cheapest 27 inch gaming monitor"` |

Returns:

```json
{ "errand_id": "<32 hex characters>", "status": "queued", "message": "Started. Check get_status in a few seconds." }
```

Errors: "I'm busy with other errands. Please try again shortly." (two errands already running), and "The errand limit has been reached. Please try again later." (20 per hour or 100 per day).

### `get_status(errand_id)`

Progress of one errand.

| Input | Type | Rules |
|---|---|---|
| `errand_id` | string | The id from `start_errand` (32 lowercase hex characters) |

Returns:

```json
{
  "errand_id": "…",
  "status": "running",
  "category": "smartphones",
  "progress": { "evomag": "ok", "altex": "running", "mediagalaxy": "ok", "vexio": "running" }
}
```

`status` is one of `queued`, `planning`, `running`, `judging`, `done`, `failed`. Each shop in `progress` is `pending`, `running`, `ok`, `empty` (nothing matched), `blocked` (the shop refused automated access) or `error`. `category` is `null` until the planner has answered.

Error: "Unknown errand." for an id that is malformed or not found.

### `get_result(errand_id)`

The finished comparison. Same input as `get_status`.

While the errand is still working: `{ "ready": false, "status": "<state>" }`.

If it failed: `{ "ready": true, "status": "failed", "spoken_summary": "Sorry, I couldn't finish that errand.", "error": "…" }`.

When done:

```json
{
  "ready": true,
  "status": "done",
  "request": "cheapest nokia phone",
  "spoken_summary": "The cheapest Nokia phone I found is …",
  "plan": { "supported": true, "category": "smartphones", "site_ids": ["evomag", "altex", "mediagalaxy", "vexio"], "focus": "nokia", "reason": "" },
  "sites": [
    {
      "site_id": "evomag", "site_name": "evomag.ro", "source_url": "https://…",
      "status": "ok", "pages_read": 1, "sorted_by_price": true, "error": "",
      "offers": [ { "name": "…", "price": 79.99, "currency": "RON", "specs": "" } ]
    }
  ],
  "verdict": { "summary": "…", "best_site_id": "evomag", "best_offer_name": "…", "caveats": "…" },
  "sites_asked": 4,
  "sites_compared": 3,
  "usage": { "calls": 7, "input_tokens": 36109, "output_tokens": 4386, "estimated_cost_usd": 0.0097 }
}
```

- `spoken_summary` is the text to read aloud: at most 400 characters, no links, no markdown.
- Offers in each shop are matching products only, cheapest first. Button 4 of the gadget shows the first offer of every shop.
- `sorted_by_price` is `true` when the shop's own cheapest-first order was used, so the first match is the cheapest in the category. When `false`, the price is the cheapest among the pages read.
- `sites_asked` and `sites_compared` are counted in code, never by a model.
- `usage.estimated_cost_usd` is an estimate from token counts.
- If the request is not a product search, `plan.supported` is `false`, `sites` is empty, `verdict` is `null`, and `spoken_summary` holds the reason.

### Other endpoint

`GET /health` answers `ok` without a token, for the platform health check.

### Where the contract is defined in the code

| What | File |
|---|---|
| Tool names, inputs, errors, `/mcp` and `/health` | `src/errand_crew/server.py` |
| Result shapes (`ErrandResult`, `SiteResult`, `ProductOffer`, `Verdict`, `Usage`) | `src/errand_crew/schemas.py` |
| Errand lifecycle, limits and the busy and rate-limit errors | `src/errand_crew/orchestrator.py` |
| Bearer-token check | `src/errand_crew/security.py` |

### Pipeline

1. **Planner (Sonnet 5.5).** Maps the request to one category and a list of shops. Its output must pass a Pydantic schema and then a code check: the category and shop ids must exist in the registry (`sites.yaml`), at most four shops are kept, and the `focus` phrase is cleaned and capped at 80 characters.
2. **Workers (Haiku 5.5), in parallel.** One `asyncio` task per shop, each with its own Kernel browser and a hard timeout of 150 s. A worker opens up to three pages of the category listing (sorted by price where the shop supports it through its URL), extracts products as structured output, and keeps only offers whose name and price really appear in the page text.
3. **Judge.** Plain code picks the cheapest offer in a single currency and builds the facts (which shops were checked, which were blocked or empty, whether the winning shop was read in price order). A model only rewords those facts for speech. Its sentence is used only if it names the same shop and the exact price and invents no other price; otherwise a template sentence is spoken.

### The desk gadget in the code

`scripts/uno_bridge.py` keeps one small state machine, the same for every button press:

```
idle -- button 1 --> typing    -- button 1 --> processing --> idle
idle -- button 2 --> listening -- button 2 --> processing --> idle
idle -- button 3 --> repeat the last answer   --> idle
idle -- button 4 --> show every shop's price  --> idle
```

Any other press is ignored, and typing or listening stops after 60 seconds. The state machine does not touch the network, the microphone, the window or the voice directly: they are passed in, which is how the tests run it with fakes. Presses made while the server is working are queued by the serial cable, so the bridge discards them when the errand ends instead of replaying them. A new request replaces the remembered answer, so button 3 never repeats the answer to a different request.

## Problems I encountered

- **Prices mapped strange:** Evomag prints `79` and `99` as separate elements, so plain text extraction turned a price of 79.99 into `7999`. Worse, our own safety check would have accepted it, because `7999` really was in the extracted text. A small script now fixes this inside the page before the text is read, and a test runs it in a real browser.
- **Forced tool choice is not available on Sonnet 5.5.** The API rejected our first approach (forcing the model to call a tool) with a 400 error. Structured output now uses automatic tool choice, an instruction to call the tool exactly once, and strict validation. Plain text or an invalid answer raises an error instead of being trusted.
- **The judge model dropped good results.** In early runs the judge sometimes returned nothing, and the assistant answered "I couldn't find matching listings" even though the workers had found offers. We moved the decision into code (the cheapest offer, which shops were checked) and let the model only reword it. If its wording disagrees with the data, a template sentence is spoken instead.
- **The cheapest product was not on the first page.** Category pages hold hundreds of products in default order, so "cheapest Samsung phone" could come back empty at a shop that did stock one. We now open each shop's price-ascending listing and read up to three pages, and the answer says when a shop was only checked over its first pages.
- **A site rule limited our options.** Evomag's `robots.txt` disallows the sorted second page, so Evomag is read on its first page only, and we respect that. Vexio cannot be sorted by link at all and, once, answered one of its pages with an access error. The result keeps what was read earlier and states which shop could not be checked.
- **A shop sometimes blocked a run.** Evomag once reported itself as blocked in one run and worked in the next, for a reason we could not determine. We log the HTTP status and size of every page we treat as blocked, report the shop as blocked in the answer, and do not try to get around it.
- **Cost is measured, not guessed.** Every Claude call is counted from the API's own usage fields. The result reports calls, tokens and an estimated cost (about one US cent per request in our tests).
- **A button on the Arduino looked pressed all the time.** A 4-leg push button has two pairs of legs connected inside, and our wiring put the pin and GND on one pair, so the pin was always tied to GND. Wiring them to diagonal legs fixed it. A loose ground wire made the pin pick up noise and react to a finger near the button.
- **The second press of the same button never arrived.** Our first sketch locked the buttons after the first press, until the PC said it was done, so "press 1 again to send" could not work. The Uno now reports every press and the PC decides what it means.
- **Typing in the terminal needs Enter.** A terminal only hands a line to the program after Enter, which did not fit "press the button to send". Typing now happens in a small window that the button controls.
- **The serial port was busy.** Only one program can open the Uno's port, so the Arduino IDE's Serial Monitor blocks the bridge, and opening the port resets the Uno, so the bridge waits two seconds before talking to it.
- **Speech models invent words from silence.** Whisper can return text for a recording that is only background noise. Recordings shorter than 0.4 seconds or quieter than a threshold are not transcribed, and the bridge says it did not understand.

## Security model: prompt injection and AI hallucinations

Errand Crew reads web pages written by strangers and lets language models handle that text, which is exactly where **prompt injection** and **AI hallucinations** come from. We do not rely on a model behaving well. The limits are in code.

### Protection against prompt injection

Both direct prompt injection (a malicious spoken request) and indirect prompt injection (instructions hidden in a shop page) are covered:

- **Least privilege.** The models have no tools, no URLs and no browser control. They only receive text and return data. Even a fully fooled model cannot browse elsewhere, click, log in or post anything.
- **URL allowlist, enforced twice.** Every URL is built from a fixed shop registry and checked against an allowlist in the server and again inside the cloud browser, which blocks any other navigation. Neither the user nor a model can supply a URL.
- **Untrusted input is marked as data.** The request and the page text are wrapped as untrusted content, and the models are told never to follow instructions found in them.
- **Validated plans.** The planner's answer must pass a schema and a code check: only categories and shops from the registry are accepted, at most four shops are used, and the focus phrase is cleaned and capped.
- **Early screening.** Obvious attack text in a request ("ignore all previous instructions", "waste tokens") is turned away before any model is called. This is only an extra layer, since a rephrased attack can get past a pattern, so the limits above are what we depend on.
- **Bounded inputs and outputs.** Requests are limited to 300 characters, page text to 15,000 characters, and every model call has a token cap, so an attack cannot make a request expensive.

### Protection against AI hallucinations

- **Grounding.** A product is kept only if its name and price really appear in the page text. A model cannot invent a listing.
- **The code decides, not the model.** The cheapest offer is chosen in code. A model only puts the result into words, and its sentence is used only if it names the same shop and the exact price and invents no other price, no link and no markdown. Otherwise a template sentence is spoken.
- **Strict structured output.** Every model answer is validated against a schema. Plain text or an invalid answer is rejected, not trusted.
- **Plausibility check.** A fake listing on a page would pass grounding, because its text is really there. So a price far below all other offers is flagged in the spoken answer, in the code's own words.
- **Honest coverage.** The answer says what could not be checked: a blocked shop, an empty result, or a shop read only over its first pages.

### Access and abuse control

- A per-client bearer token is required (compared in constant time). Each client has its own token, so one can be revoked without affecting the others.
- Rate limits: two errands at once, 20 per hour and 100 per day.
- The service is read-only: it never logs in, adds to a cart or submits a form.
- No secrets live in the repository. Keys and tokens come from environment variables.

### The desk gadget

- The bridge only talks to the one server address you give it, with a token read from an environment variable. The token is never stored in a file.
- Serial messages are limited: the Uno can only send `ASK:` lines with a button number, and anything else is ignored. The LCD only shows plain ASCII text.
- The text read aloud comes from the server's answer, which may contain words from a shop page. It is passed to the voice program on its standard input, never inside a command line, so it cannot be run as a command. It is limited to ASCII and 1,000 characters.
- Speech is transcribed locally. Your voice is not sent to any cloud service.
- A request typed or spoken at the gadget passes through exactly the same checks as any other client's request.

These measures reduce the risk, they do not remove it. A convincing fake price on a page can still reach the answer, which is why it comes with a warning when it looks out of line.

### Tests

More than 200 automated tests run without network or cost, using a scripted model, a fake browser, a fake Arduino port, a fake microphone and a fake voice. They cover the planner, workers, judge, URL allowlist, pagination, the Claude wrapper, rate limits, prompt-injection attempts in both the request and a shop page, and the Arduino gadget's buttons, window, speech input and spoken output.

### Known limits

Four shops and five categories. State and rate-limit counters are in memory and reset when the server restarts. Prices are read at request time and may be out of date. Shop terms of service should be checked before running at scale.

The server speaks standard MCP over Streamable HTTP with bearer-token authentication. We tested it with an MCP client that simulates a voice assistant, not on an Alexa+ device, and we did not verify Alexa+'s own authentication requirements.

On the desk gadget: the LCD shows two lines of 16 characters, so product names do not fit and the details button shows only shop names and prices rounded to whole lei. The answers are in English, and the voice that reads them is the operating system's own, so its quality depends on the computer. Whisper can mishear product names, so the window shows what it heard. The last answer used by buttons 3 and 4 is kept in memory only. The gadget needs a PC next to it: the Uno itself cannot connect to the internet. The bridge was developed against a real Uno on Windows; Linux and macOS support follows the same code but is less tested, and reading answers aloud was tested with a simulated voice program in the automated tests.


# Co-Author: Claude Code.

# Errand Crew - an observable six-agent AI workflow

**Alexa+ MCP server that sends parallel browser agents across online shops, compares options, and speaks the answer back.**

### The MCP server uses a six-agent AI workflow

- **A planner** (Claude Sonnet 5.5) turns the spoken request into a plan.
- **Four worker agents** (Claude Haiku 5.5) browse Evomag, Altex, MediaGalaxy and Vexio in parallel, each in its own cloud browser.
- **The judge** picks the cheapest match in code. A model (Claude Haiku 5.5) only words the result for speech, so the spoken answer never depends on a model behaving.

**You can watch the agents work.** The browsers run on the [Kernel](https://www.kernel.sh) cloud browser infrastructure, as shown in the demo video below. If you run the server yourself with your own Kernel key and `KERNEL_HEADLESS=false`, you can see the four browsers live in the Kernel dashboard.

The agents can only visit shops from a fixed allowlist, and everything they read on a page is treated as data, never as instructions.

<img width="2000" height="1120" alt="Image" src="https://github.com/user-attachments/assets/c98256af-f620-46ad-b8e3-2c8ffc7c06a3" />



## How it works

Comparing prices means opening shop after shop and scrolling. Errand Crew does that part for you, while you just ask a question out loud.

Say you want a cheap phone. You ask your voice assistant, and from there it takes about half a minute! Isn't it great?


## Build and run

You need your own [Anthropic](https://console.anthropic.com) API key and [Kernel](https://www.kernel.sh) API key in both options.

### Environment variables

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Your Claude API key |
| `KERNEL_API_KEY` | Your Kernel API key |
| `ERRAND_CREW_TOKENS` | One bearer token per client, as `name:token,name:token`. Each token needs at least 24 characters and no commas, and all tokens must differ. Remove a pair to revoke that client. |
| `KERNEL_HEADLESS` | Optional. `false` (the default) opens browsers with a screen you can watch in the Kernel dashboard. `true` runs them headless, which is faster and cheaper. |

Generate a token with any random string tool, for example `openssl rand -hex 16`.

### Option 1: Deploy on Render

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

Try it with the demo client (see below), using the `/mcp` URL of your service.

### Option 2: Run locally

```bash
git clone https://github.com/kantorarthur/errand_crew_amazon_hackaton.git
cd errand_crew_amazon_hackaton
python -m venv .venv
```

Install the dependencies (on Windows use `.venv\Scripts\python`, on macOS and Linux use `.venv/bin/python`):

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Set the environment variables, then start the server. macOS and Linux:

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

The server listens on `http://localhost:8000`, with the MCP endpoint at `/mcp` and a health check at `/health`.

### Try it: the demo client

The demo client behaves like a voice assistant: it starts an errand, polls its status and prints the spoken summary and the Claude usage. In a second terminal, set `MCP_TOKEN` to the token from `ERRAND_CREW_TOKENS`:

```bash
export MCP_TOKEN="<your-random-token>"      # PowerShell: $env:MCP_TOKEN = "<your-random-token>"
.venv/bin/python scripts/demo_client.py "cheapest nokia phone" http://localhost:8000/mcp
```

For a Render deployment, pass its URL instead: `https://<your-service>.onrender.com/mcp`.

### Run the tests

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests use a scripted model and a fake browser, so they need no network, no keys and cost nothing.


## Dependencies

**Python:** 3.13 on Render (`PYTHON_VERSION=3.13.5`); the tests also run on 3.14.

### Runtime (`requirements.txt`, pinned)

| Package | Version | What it is used for |
|---|---|---|
| `fastmcp` | 4.1.3 | MCP server over Streamable HTTP, bearer-token auth hook, MCP client in the demo script |
| `anthropic` | 2.1.0 | Claude API client (planner, workers and judge wording) |
| `kernel` | 0.129.0 | Kernel SDK: creates and deletes the cloud browsers and runs Playwright code in them |
| `pydantic` | 2.14.1 | Validation of every data shape, including everything a model returns |
| `PyYAML` | 6.0.3 | Loads the shop registry (`sites.yaml`) |
| `uvicorn` | 0.54.0 | ASGI server that runs the app |

Standard library: `asyncio`, `hmac`, `statistics`, `contextvars`, `dataclasses`, `urllib`, `re`, `json`, `logging`.

### Development (`requirements-dev.txt`)

| Package | Version | Use |
|---|---|---|
| `pytest` | 9.1.1 | Test runner |
| `pytest-asyncio` | 1.4.0 | Async tests |
| `httpx` | 0.28.1 | Test client |

One test runs a real Chromium through `playwright` to check the price-decimal fix. It is optional and is skipped when Playwright or Chromium is not installed.

### External services

| Service | Role | Credential |
|---|---|---|
| Anthropic API | Claude Sonnet 5.5 (planner), Claude Haiku 5.5 (workers, judge wording) | `ANTHROPIC_API_KEY` |
| Kernel | Cloud browsers, one per shop | `KERNEL_API_KEY` |
| Render | Hosting for the MCP server | none in the code; secrets are set in its dashboard |

Clients authenticate to the server with a bearer token from `ERRAND_CREW_TOKENS`. Nothing else is needed: no database, no queue, no extra cloud service.



## Technical overview

**Stack:** Python, [FastMCP](https://gofastmcp.com) (MCP over Streamable HTTP), the Anthropic API (Claude Sonnet 5.5 and Claude Haiku 5.5), Kernel.sh API, deployed on Render.

## MCP tools (the interface)

Defined in [`src/errand_crew/server.py`](src/errand_crew/server.py), served at `/mcp` over Streamable HTTP. Every call needs `Authorization: Bearer <token>`. All three tools are marked read-only: they never log in, buy or submit anything.

A voice assistant should call `start_errand`, poll `get_status` every few seconds, then read `spoken_summary` from `get_result`.

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
- Offers in each shop are matching products only, cheapest first.
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


## Problems I encountered

- **Prices mapped strange:** Evomag prints `79` and `99` as separate elements, so plain text extraction turned a price of 79.99 into `7999`. Worse, our own safety check would have accepted it, because `7999` really was in the extracted text. A small script now fixes this inside the page before the text is read, and a test runs it in a real browser.
- **Forced tool choice is not available on Sonnet 5.5.** The API rejected our first approach (forcing the model to call a tool) with a 400 error. Structured output now uses automatic tool choice, an instruction to call the tool exactly once, and strict validation. Plain text or an invalid answer raises an error instead of being trusted.
- **The judge model dropped good results.** In early runs the judge sometimes returned nothing, and the assistant answered "I couldn't find matching listings" even though the workers had found offers. We moved the decision into code (the cheapest offer, which shops were checked) and let the model only reword it. If its wording disagrees with the data, a template sentence is spoken instead.
- **The cheapest product was not on the first page.** Category pages hold hundreds of products in default order, so "cheapest Samsung phone" could come back empty at a shop that did stock one. We now open each shop's price-ascending listing and read up to three pages, and the answer says when a shop was only checked over its first pages.
- **A site rule limited our options.** Evomag's `robots.txt` disallows the sorted second page, so Evomag is read on its first page only, and we respect that. Vexio cannot be sorted by link at all and, once, answered one of its pages with an access error. The result keeps what was read earlier and states which shop could not be checked.
- **A shop sometimes blocked a run.** Evomag once reported itself as blocked in one run and worked in the next, for a reason we could not determine. We log the HTTP status and size of every page we treat as blocked, report the shop as blocked in the answer, and do not try to get around it.
- **Cost is measured, not guessed.** Every Claude call is counted from the API's own usage fields. The result reports calls, tokens and an estimated cost (about one US cent per request in our tests).


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

These measures reduce the risk, they do not remove it. A convincing fake price on a page can still reach the answer, which is why it comes with a warning when it looks out of line.

### Tests

91 automated tests run without network or cost, using a scripted model and a fake browser. They cover the planner, workers, judge, URL allowlist, pagination, the Claude wrapper, rate limits, and prompt-injection attempts in both the request and a shop page.

### Known limits

Four shops and five categories. State and rate-limit counters are in memory and reset when the server restarts. Prices are read at request time and may be out of date. Shop terms of service should be checked before running at scale. The server is built to Alexa+'s MCP requirements, but we tested it with an MCP client that simulates a voice assistant, not on an Alexa+ device.



"""Demo client: behaves like a voice assistant talking to the Errand Crew MCP server.

It calls start_errand, polls get_status, then reads spoken_summary from get_result.
The bearer token is read from the environment and never printed.

  $env:MCP_TOKEN = "<one of the server's client tokens>"
  python scripts/demo_client.py "cheapest 27 inch gaming monitor"
  python scripts/demo_client.py "cheapest nokia phone" http://localhost:8000/mcp
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from fastmcp import Client
from fastmcp.exceptions import ToolError

POLL_SECONDS = 2
GIVE_UP_AFTER = 180


async def main() -> int:
    request = sys.argv[1] if len(sys.argv) > 1 else "cheapest 27 inch gaming monitor"
    url = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("MCP_URL", "http://localhost:8000/mcp")
    token = os.environ.get("MCP_TOKEN", "")
    if not token:
        print("Set MCP_TOKEN in this terminal first (one of the server's client tokens).")
        return 2

    started = time.time()
    async with Client(url, auth=token) as client:
        tools = sorted(t.name for t in await client.list_tools())
        print("Connected. Tools:", ", ".join(tools))
        print(f'\nUser: "{request}"')
        try:
            start = (await client.call_tool("start_errand", {"request": request})).data
        except ToolError as exc:
            print("Server refused:", exc)
            return 1
        errand_id = start["errand_id"]
        print(f"[{time.time() - started:5.1f}s] started {errand_id[:8]}...")

        last = None
        while time.time() - started < GIVE_UP_AFTER:
            status = (await client.call_tool("get_status", {"errand_id": errand_id})).data
            snapshot = (status["status"], str(status.get("progress")))
            if snapshot != last:
                print(f"[{time.time() - started:5.1f}s] {status['status']:8} {status.get('progress')}")
                last = snapshot
            if status["status"] in ("done", "failed"):
                break
            await asyncio.sleep(POLL_SECONDS)
        else:
            print("Gave up waiting.")
            return 1

        result = (await client.call_tool("get_result", {"errand_id": errand_id})).data

    print(f"\nAlexa says: {result['spoken_summary']}")
    for site in result.get("sites", []):
        top = site["offers"][0] if site["offers"] else None
        line = f"  {site['site_name']:16} {site['status']:8}"
        if top:
            line += f" {top['price']:>9.2f} {top['currency']}  {top['name']}"
        print(line)
    if "sites_compared" in result:
        print(f"Compared {result['sites_compared']} of {result['sites_asked']} shops.")
    return 0 if result.get("status") == "done" else 1


def run() -> int:
    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Could not talk to the server ({type(exc).__name__}). "
              "Is it running, and are the URL and MCP_TOKEN right?")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())

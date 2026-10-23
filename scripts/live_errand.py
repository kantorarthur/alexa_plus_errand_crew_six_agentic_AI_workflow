"""Live run of the WHOLE pipeline (planner -> parallel workers -> judge), no MCP server.

Uses real Claude and real Kernel browsers, so it costs money (roughly half a cent to a
cent per run, an estimate, not measured). Keys are read from the environment and never
printed.

  python scripts/live_errand.py
  python scripts/live_errand.py "cheapest 27 inch gaming monitor"
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from errand_crew.config import Settings  # noqa: E402
from errand_crew.server import build_orchestrator  # noqa: E402


async def main() -> int:
    request = sys.argv[1] if len(sys.argv) > 1 else "cheapest 27 inch gaming monitor"
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    kernel_key = os.environ.get("KERNEL_API_KEY", "")
    if not anthropic_key or not kernel_key:
        print("Set ANTHROPIC_API_KEY and KERNEL_API_KEY in this terminal first.")
        return 2

    logging.basicConfig(level=logging.WARNING)
    # The token is only a placeholder: there is no server here, so nothing checks it.
    settings = Settings(
        client_tokens={"live": "x" * 24},
        anthropic_api_key=anthropic_key,
        kernel_api_key=kernel_key,
    )
    orch = build_orchestrator(settings)

    print("Request:", request)
    started = time.time()
    errand = orch.start(request)
    last = None
    while errand.state not in ("done", "failed"):
        snapshot = (errand.state, dict(errand.progress))
        if snapshot != last:
            print(f"[{time.time() - started:5.1f}s] {errand.state:8} {errand.progress}")
            last = snapshot
        await asyncio.sleep(1)
    await orch.wait_idle()
    print(f"[{time.time() - started:5.1f}s] {errand.state}")

    if errand.state == "failed" or errand.result is None:
        print("Errand failed:", errand.error)
        return 1

    result = errand.result
    plan = result.plan
    print(f"\nPlan: supported={plan.supported} category={plan.category} "
          f"sites={plan.site_ids} focus={plan.focus!r}")
    for site in result.sites:
        order = "cheapest-first" if site.sorted_by_price else "default order"
        print(f"\n{site.site_name}: {site.status} ({site.pages_read} pages, {order})")
        if site.error:
            print("  error:", site.error)
        for offer in site.offers[:3]:
            print(f"  {offer.price:>10.2f} {offer.currency}  {offer.name}")
    print(f"\nCompared {result.sites_compared} of {result.sites_asked} shops.")
    if result.verdict:
        print("Best:", result.verdict.best_site_id, "|", result.verdict.best_offer_name)
        if result.verdict.caveats:
            print("Caveats:", result.verdict.caveats)
    print("\nSPOKEN SUMMARY:\n", result.spoken_summary)
    if result.usage:
        u = result.usage
        print(f"\nClaude usage: {u.calls} calls, {u.input_tokens} in / {u.output_tokens} out tokens, "
              f"about ${u.estimated_cost_usd} (estimate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""Live check of ONE worker against ONE shop (real Kernel browser + real Claude).

Costs about a cent. Keys are read from the environment and never printed.

  python scripts/live_check_one_worker.py                      # mediagalaxy / monitors
  python scripts/live_check_one_worker.py altex laptops "gaming"
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from errand_crew.browser import KernelFetcher  # noqa: E402
from errand_crew.config import Settings  # noqa: E402
from errand_crew.llm import ClaudeLLM  # noqa: E402
from errand_crew.registry import Registry  # noqa: E402
from errand_crew.workers import Worker  # noqa: E402


async def main() -> int:
    site_id = sys.argv[1] if len(sys.argv) > 1 else "mediagalaxy"
    category = sys.argv[2] if len(sys.argv) > 2 else "monitors"
    focus = sys.argv[3] if len(sys.argv) > 3 else "27 inch monitor"

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    kernel_key = os.environ.get("KERNEL_API_KEY", "")
    if not anthropic_key or not kernel_key:
        print("Set ANTHROPIC_API_KEY and KERNEL_API_KEY in this terminal first.")
        return 2

    registry = Registry.load()
    site = registry.site(site_id)
    if site is None or category not in site.categories:
        print(f"No such site/category. Sites: {[s.id for s in registry.sites_for(category)]}")
        return 2

    defaults = Settings(client_tokens={"live": "x" * 24})
    worker = Worker(
        KernelFetcher(kernel_key, registry, defaults.max_page_chars),
        ClaudeLLM(anthropic_key),
        registry,
        defaults.worker_model,
    )
    print(f"{site.id} / {category} / focus={focus!r}")
    print("page 1 URL:", registry.page_url(site.id, category, 1))
    started = time.time()
    result = await asyncio.wait_for(worker.run(site, category, focus), defaults.worker_timeout_s)
    print(f"status={result.status} pages_read={result.pages_read} "
          f"sorted_by_price={result.sorted_by_price} time={time.time() - started:.1f}s")
    if result.error:
        print("error:", result.error)
    for offer in result.offers:
        print(f"  {offer.price:>10.2f} {offer.currency}  {offer.name}")
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

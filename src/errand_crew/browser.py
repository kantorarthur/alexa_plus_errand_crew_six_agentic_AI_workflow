"""Cloud browser access through Kernel.

The browser only ever opens one registry URL and returns its visible text. No LLM
controls the browser: navigation is fixed code, so a malicious page cannot make an
agent click, type, submit or travel anywhere.
"""

from __future__ import annotations

import json
import logging
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from kernel import AsyncKernel

from .registry import Registry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageFetch:
    status: int
    final_url: str
    text: str


class PageReader(Protocol):
    async def fetch(self, url: str) -> PageFetch: ...


class BrowserFetcher(Protocol):
    def open(self) -> AbstractAsyncContextManager[PageReader]:
        """One browser for several pages of the same site; always released on exit."""
        ...


# Some shops print the decimals of a price as a superscript, e.g. 79<sup>99</sup> lei, and
# innerText then glues them into "7999". Runs in the page before the text is read: turns
# that markup into "79,99 lei". Only a two-digit <sup> that directly follows a digit and sits
# in an element that shows a currency is touched.
FIX_DECIMALS_JS = """() => {
  document.querySelectorAll('sup').forEach((s) => {
    if (!/^\\d{2}$/.test((s.textContent || '').trim())) return;
    const prev = s.previousSibling;
    if (!prev || prev.nodeType !== 3 || !/\\d\\s*$/.test(prev.textContent)) return;
    const box = s.parentElement ? (s.parentElement.innerText || '') : '';
    if (!/lei|ron/i.test(box)) return;
    prev.textContent = prev.textContent.replace(/\\s+$/, '');
    s.insertAdjacentText('beforebegin', ',');
    s.insertAdjacentText('afterend', ' ');
  });
}"""

# Runs inside the Kernel VM. `page` and `context` are provided by Kernel.
# Main-frame navigations away from the allowlisted domains are aborted.
_FETCH_JS = """
const allowed = __ALLOWED__;
const ok = (u) => {
  try {
    const h = new URL(u).hostname.toLowerCase();
    return allowed.some((d) => h === d || h.endsWith('.' + d));
  } catch (e) { return false; }
};
await context.unroute('**/*').catch(() => {});
await context.route('**/*', (route) => {
  const req = route.request();
  if (req.isNavigationRequest() && req.frame() === page.mainFrame() && !ok(req.url())) {
    return route.abort();
  }
  return route.continue();
});
const resp = await page.goto(__URL__, { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.waitForTimeout(2500);
await page.evaluate(__FIX_DECIMALS__);
const text = await page.evaluate((n) => (document.body ? document.body.innerText.slice(0, n) : ''), __MAX__);
return JSON.stringify({ status: resp ? resp.status() : 0, finalUrl: page.url(), text });
"""


def build_fetch_js(url: str, allowed_domains: list[str], max_chars: int) -> str:
    return (
        _FETCH_JS.replace("__ALLOWED__", json.dumps(allowed_domains))
        .replace("__URL__", json.dumps(url))
        .replace("__MAX__", str(int(max_chars)))
        .replace("__FIX_DECIMALS__", FIX_DECIMALS_JS)
    )


class KernelFetcher:
    def __init__(self, api_key: str, registry: Registry, max_chars: int) -> None:
        self._kernel = AsyncKernel(api_key=api_key or None)
        self._registry = registry
        self._max_chars = max_chars

    @asynccontextmanager
    async def open(self):
        """Create one Kernel browser, reuse it for every page, delete it at the end."""
        browser = await self._kernel.browsers.create(headless=True, timeout_seconds=180)
        try:
            yield _KernelPages(self, browser.session_id)
        finally:
            # Always release the paid browser, even on error or timeout.
            try:
                await self._kernel.browsers.delete_by_id(browser.session_id)
            except Exception:  # noqa: BLE001
                log.warning("failed to delete Kernel browser %s", browser.session_id)

    async def fetch_in(self, session_id: str, url: str) -> PageFetch:
        if not self._registry.is_allowed_url(url):
            raise ValueError("URL is not in the allowlist")
        code = build_fetch_js(url, self._registry.domains, self._max_chars)
        resp = await self._kernel.browsers.playwright.execute(
            session_id, code=code, timeout_sec=60
        )
        if not resp.success:
            raise RuntimeError("browser step failed")
        payload = resp.result
        data = json.loads(payload) if isinstance(payload, str) else payload
        final_url = str(data.get("finalUrl", ""))
        if not self._registry.is_allowed_url(final_url):
            raise RuntimeError("browser ended on a non-allowlisted page")
        return PageFetch(
            status=int(data.get("status", 0)),
            final_url=final_url,
            text=str(data.get("text", ""))[: self._max_chars],
        )


class _KernelPages:
    def __init__(self, fetcher: KernelFetcher, session_id: str) -> None:
        self._fetcher = fetcher
        self._session_id = session_id

    async def fetch(self, url: str) -> PageFetch:
        return await self._fetcher.fetch_in(self._session_id, url)

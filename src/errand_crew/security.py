"""Bearer-token auth, rate limiting and page-text screening."""

from __future__ import annotations

import hmac
import re
import time
from collections import deque

from fastmcp.server.auth import AccessToken, TokenVerifier

ERRAND_ID_RE = re.compile(r"^[0-9a-f]{32}$")

BLOCK_MARKERS = (
    "captcha",
    "verify you are human",
    "access denied",
    "unusual traffic",
    "robot or human",
    "cloudflare",
    "are you a robot",
)


class BearerTokenVerifier(TokenVerifier):
    """Accepts one secret per client. The client's NAME, never its secret, is what the
    rest of the server sees (for logs), so one client can be revoked on its own."""

    def __init__(self, tokens: dict[str, str]) -> None:
        super().__init__()
        self._tokens = [(name, secret.encode()) for name, secret in tokens.items()]

    async def verify_token(self, token: str) -> AccessToken | None:
        candidate = token.encode()
        matched: str | None = None
        # Compare against every client with no early exit, so timing reveals nothing.
        for name, secret in self._tokens:
            if hmac.compare_digest(candidate, secret):
                matched = name
        if matched is None:
            return None
        return AccessToken(token=token, client_id=matched, scopes=[])


class RateLimitError(Exception):
    pass


class SlidingWindowLimiter:
    """At most `limit` events in any `window_s` seconds (in-memory, single process)."""

    def __init__(self, limit: int, window_s: float, clock=time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._events: deque[float] = deque()

    def _trim(self, now: float) -> None:
        while self._events and now - self._events[0] >= self.window_s:
            self._events.popleft()

    def check(self) -> bool:
        self._trim(self._clock())
        return len(self._events) < self.limit

    def record(self) -> None:
        self._events.append(self._clock())


def looks_blocked(text: str, status: int) -> bool:
    """Cheap, deterministic pre-check before any LLM sees the page."""
    if status in (401, 403, 429, 503):
        return True
    head = text[:3000].lower()
    if len(text.strip()) < 400 and any(m in head for m in BLOCK_MARKERS):
        return True
    return False


def grounded(name: str, price: float, page_text: str) -> bool:
    """An offer is kept only if its name and price actually appear in the page text.

    Guards against hallucinated or injected listings: the LLM can only report what the
    page really showed.
    """
    low = page_text.lower()
    tokens = [t for t in re.split(r"\s+", name.lower().strip()) if t]
    if not tokens or not all(t in low for t in tokens[:2]):
        return False
    return _price_pattern(price).search(page_text) is not None


def _price_pattern(price: float) -> re.Pattern[str]:
    """Match the integer part as the page would print it: 3499, 3.499 or 3 499."""
    digits = str(int(price))
    groups: list[str] = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    body = r"[.\s ]?".join(groups)
    return re.compile(r"(?<![\d.,])" + body + r"(?!\d)")

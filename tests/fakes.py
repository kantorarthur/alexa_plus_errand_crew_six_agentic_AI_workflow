"""Test doubles: a scripted LLM and a fake browser. No network, no cost."""

from __future__ import annotations

from errand_crew.browser import PageFetch
from errand_crew.config import Settings
from errand_crew.judge import Judge
from errand_crew.orchestrator import Orchestrator
from errand_crew.planner import Planner
from errand_crew.registry import Registry
from errand_crew.schemas import ExtractedOffer, Narration, Plan, ProductOffer, Verdict, WorkerOutput
from errand_crew.workers import Worker

TOKEN = "t" * 32


class FakeLLM:
    """Returns a prepared object (or calls a prepared function) per tool name."""

    def __init__(self, **by_tool):
        self.by_tool = by_tool
        self.calls: list[dict] = []

    async def structured(self, *, model, system, user, schema, tool_name, max_tokens=1024):
        self.calls.append({"tool": tool_name, "model": model, "system": system, "user": user})
        item = self.by_tool[tool_name]
        out = item(user) if callable(item) else item
        if isinstance(out, Exception):
            raise out
        return out


class FakeFetcher:
    def __init__(self, pages: dict[str, PageFetch | Exception]):
        self.pages = pages
        self.fetched: list[str] = []
        self.opened = 0
        self.closed = 0

    def open(self):
        fetcher = self

        class _Ctx:
            async def __aenter__(self):
                fetcher.opened += 1
                return fetcher

            async def __aexit__(self, *exc):
                fetcher.closed += 1

        return _Ctx()

    async def fetch(self, url: str) -> PageFetch:
        self.fetched.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


def offer(name: str, price: float, matches: bool = True) -> ExtractedOffer:
    return ExtractedOffer(name=name, price=price, matches_request=matches)


def listing_text(*items: tuple[str, str]) -> str:
    rows = "\n".join(f"{name}\n{price} lei\nAdauga in cos" for name, price in items)
    return "Laptopuri\nSorteaza\n" + rows + "\n" + ("Filtre si alte detalii\n" * 30)


def make_settings(**overrides) -> Settings:
    return Settings(client_tokens={"demo": TOKEN}, **overrides)


def make_orchestrator(llm, fetcher, settings: Settings | None = None) -> Orchestrator:
    settings = settings or make_settings()
    registry = Registry.load()
    return Orchestrator(
        settings,
        registry,
        Planner(llm, registry, "planner-model", settings.max_sites_per_errand),
        Worker(fetcher, llm, registry, "worker-model"),
        Judge(llm, "judge-model"),
    )


__all__ = [
    "FakeLLM",
    "FakeFetcher",
    "PageFetch",
    "Plan",
    "ProductOffer",
    "Narration",
    "Verdict",
    "WorkerOutput",
    "ExtractedOffer",
    "listing_text",
    "offer",
    "make_orchestrator",
    "make_settings",
    "TOKEN",
]

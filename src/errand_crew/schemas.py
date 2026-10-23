"""Data shapes. Everything an LLM returns is validated against these before use."""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field, computed_field

Currency = Literal["RON", "EUR", "USD"]

# How one site's attempt ended. The judge sees this for every site it asked.
SiteStatus = Literal["ok", "blocked", "empty", "error"]
# Live progress while an errand runs: the final statuses plus the two in-flight ones.
SiteState = Literal["pending", "running", "ok", "blocked", "empty", "error"]
ErrandState = Literal["queued", "planning", "running", "judging", "done", "failed"]


class Plan(BaseModel):
    """Planner output: which category to look at and which registry sites to ask."""

    supported: bool = Field(description="False if the request is not a product search.")
    category: str | None = Field(default=None, max_length=40)
    site_ids: list[str] = Field(default_factory=list, max_length=6)
    focus: str = Field(
        default="",
        max_length=120,
        description="Short phrase workers use to prioritise listings, e.g. '27 inch gaming'.",
    )
    reason: str = Field(default="", max_length=300)


class ProductOffer(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    price: float = Field(gt=0, lt=1_000_000)
    currency: Currency = "RON"
    specs: str = Field(default="", max_length=200)


class ExtractedOffer(ProductOffer):
    """An offer as the worker's LLM reports it, with its own verdict on the request."""

    matches_request: bool = Field(
        description="True only if this product satisfies the user's focus (type, size, ...)."
    )


class WorkerOutput(BaseModel):
    """What a worker's LLM may return. Nothing else leaves the worker."""

    blocked: bool = False
    offers: list[ExtractedOffer] = Field(default_factory=list, max_length=8)


class SiteResult(BaseModel):
    site_id: str
    site_name: str
    source_url: str
    status: SiteStatus
    # Matching offers only, cheapest first.
    offers: list[ProductOffer] = Field(default_factory=list)
    pages_read: int = 0
    # True when the shop's own cheapest-first order was used, so the first match is the
    # cheapest in the whole category. False: cheapest among the pages read only.
    sorted_by_price: bool = False
    error: str = Field(default="", max_length=200)


class Narration(BaseModel):
    """Model-written wording of facts the code already decided."""

    summary: str = Field(description="One or two short spoken sentences.")


class Verdict(BaseModel):
    summary: str = Field(
        max_length=400,
        description="At most two short sentences, plain speech, no markdown or URLs.",
    )
    best_site_id: str | None = None
    best_offer_name: str | None = Field(default=None, max_length=160)
    caveats: str = Field(default="", max_length=300)


class Usage(BaseModel):
    """Claude tokens used by one errand, counted from the API's own usage fields."""

    calls: int
    input_tokens: int
    output_tokens: int
    # Estimate from the price table in llm.py; None if a model has no known price.
    estimated_cost_usd: float | None = None


class ErrandResult(BaseModel):
    request: str
    plan: Plan
    sites: list[SiteResult]
    verdict: Verdict | None
    spoken_summary: str
    usage: Usage | None = None

    # Counted in code, never by a model, so the coverage claim is always true.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def sites_asked(self) -> int:
        return len(self.sites)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sites_compared(self) -> int:
        return sum(1 for s in self.sites if s.status == "ok")


class Errand(BaseModel):
    id: str
    request: str
    state: ErrandState = "queued"
    created_at: float = Field(default_factory=time.time)
    plan: Plan | None = None
    progress: dict[str, SiteState] = Field(default_factory=dict)
    result: ErrandResult | None = None
    error: str = ""

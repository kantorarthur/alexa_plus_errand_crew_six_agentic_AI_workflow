"""Judge agent: compares validated offers and writes a speakable summary."""

from __future__ import annotations

import json

from .llm import LLMError, StructuredLLM
from .schemas import Plan, SiteResult, Verdict

NO_RESULT = "I couldn't find matching listings right now. Please try again in a moment."

SYSTEM = """You compare product offers gathered from several retailers for a voice assistant.
Use ONLY the JSON data provided. Never add products, prices or shops that are not in it.
Write at most two short sentences a person can listen to: no markdown, no URLs, no lists.
Name the best-value offer (lowest price) and its shop. Each shop has `order`:
"cheapest_first" means its first offer is the cheapest in the whole category that fits;
"as_listed" means the offers are only the cheapest among `pages_read` pages of its
default order, so say "among the first pages" and do not claim it is the overall cheapest.
Shops listed with a status other than ok had no usable result; mention in `caveats` that
they were skipped. If the offers are clearly different products or specs, say so in
`caveats`. Pick best_site_id and best_offer_name exactly as they appear in the data."""


class Judge:
    def __init__(self, llm: StructuredLLM, model: str) -> None:
        self._llm = llm
        self._model = model

    async def judge(
        self, request: str, plan: Plan, results: list[SiteResult]
    ) -> Verdict | None:
        with_offers = [r for r in results if r.offers]
        if not with_offers:
            return None
        data = [
            {
                "site_id": r.site_id,
                "shop": r.site_name,
                "status": r.status,
                "pages_read": r.pages_read,
                "order": "cheapest_first" if r.sorted_by_price else "as_listed",
                "offers": [o.model_dump() for o in r.offers],
            }
            for r in results
        ]
        try:
            verdict = await self._llm.structured(
                model=self._model,
                system=SYSTEM,
                user=(
                    f"Request: {request}\nFocus: {plan.focus or 'none'}\n\n"
                    f"<data>\n{json.dumps(data, ensure_ascii=False)}\n</data>"
                ),
                schema=Verdict,
                tool_name="submit_verdict",
                max_tokens=500,
            )
        except LLMError:
            return None
        return self._check(verdict, with_offers)

    @staticmethod
    def _check(verdict: Verdict, with_offers: list[SiteResult]) -> Verdict:
        """The judge may only point at an offer that really exists."""
        site = next((r for r in with_offers if r.site_id == verdict.best_site_id), None)
        if site is None or verdict.best_offer_name not in {o.name for o in site.offers}:
            return verdict.model_copy(update={"best_site_id": None, "best_offer_name": None})
        return verdict

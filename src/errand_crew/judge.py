"""Judge: the code decides, the model only words it.

Facts (which offer is cheapest, which shops were compared, whether a shop was sorted) are
computed here from validated data. A model may reword the answer for speech, but its text
is only used if it states the same shop and price as the code and invents no other price.
Otherwise a sentence built from a template is used, so the answer never depends on the
model behaving.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter

from .llm import StructuredLLM
from .schemas import Narration, Plan, ProductOffer, SiteResult, Verdict

log = logging.getLogger(__name__)

NO_RESULT = "I couldn't find matching listings right now. Please try again in a moment."
MAX_SUMMARY = 400
_SPOKEN_CURRENCY = {"RON": "lei", "EUR": "euro", "USD": "dollars"}

SYSTEM = """You turn already-decided facts about a price comparison into speech for a voice assistant.
Use ONLY the JSON facts provided. Never add products, prices or shops that are not in it.
Write at most two short sentences a person can listen to: no markdown, no URLs, no lists.
You must name the best offer's shop and state its exact price. If a caveat is listed, say it
briefly (for example "among the first pages checked")."""


# --- facts, decided in code ---------------------------------------------------


def choose_best(results: list[SiteResult]) -> tuple[SiteResult, ProductOffer] | None:
    """Cheapest offer over all shops, comparing one currency only (RON when present)."""
    pairs = [(r, o) for r in results for o in r.offers]
    if not pairs:
        return None
    counts = Counter(o.currency for _, o in pairs)
    currency = "RON" if counts.get("RON") else counts.most_common(1)[0][0]
    same = [(r, o) for r, o in pairs if o.currency == currency]
    # min() keeps the first of equal prices, i.e. the earlier shop in the plan.
    return min(same, key=lambda p: p[1].price)


def money(offer: ProductOffer) -> str:
    amount = f"{offer.price:.2f}".rstrip("0").rstrip(".")
    return f"{amount} {_SPOKEN_CURRENCY.get(offer.currency, offer.currency)}"


def caveat_facts(results: list[SiteResult], best_site: SiteResult) -> list[str]:
    facts = []
    if not best_site.sorted_by_price:
        facts.append(f"{best_site.site_name} was only checked over its first pages")
    gaps = [r.site_name for r in results if r.status != "ok"]
    if gaps:
        facts.append("no usable result from " + ", ".join(gaps))
    return facts


def template_summary(best_site: SiteResult, offer: ProductOffer, facts: list[str]) -> str:
    name = offer.name if len(offer.name) <= 90 else offer.name[:87].rstrip() + "..."
    text = f"The cheapest I found is {name} at {best_site.site_name} for {money(offer)}."
    if facts:
        text += " Note: " + "; ".join(facts) + "."
    return text[:MAX_SUMMARY]


# --- checking the model's wording ---------------------------------------------


def _parse_number(token: str) -> float | None:
    token = token.strip(".,")
    if "," in token and "." in token:
        decimal = "," if token.rfind(",") > token.rfind(".") else "."
        token = token.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in token or "." in token:
        sep = "," if "," in token else "."
        head, _, tail = token.rpartition(sep)
        token = f"{head.replace(sep, '')}.{tail}" if len(tail) != 3 or sep in head else token.replace(sep, "")
    try:
        return float(token)
    except ValueError:
        return None


def narration_ok(
    text: str, best_site: SiteResult, offer: ProductOffer, results: list[SiteResult]
) -> bool:
    """True only if the wording agrees with the code's facts and invents no price."""
    if not text or len(text) > MAX_SUMMARY or re.search(r"https?:|www\.|[*#_`\[\]]", text):
        return False
    lowered = text.lower()
    if best_site.site_name.split(".")[0].lower() not in lowered:
        return False
    known_names = " ".join(o.name for r in results for o in r.offers)
    known_prices = [o.price for r in results for o in r.offers]
    numbers = [_parse_number(t) for t in re.findall(r"\d[\d.,]*", text)]
    if not any(n is not None and abs(n - offer.price) < 0.005 for n in numbers):
        return False
    for token in re.findall(r"\d[\d.,]*", text):
        value = _parse_number(token)
        digits = len(re.sub(r"\D", "", token.split(",")[0].split(".")[0]))
        if digits < 3 or token.strip(".,") in known_names:
            continue  # small numbers (page counts) and numbers from product names
        if value is None or not any(
            abs(value - p) < 0.005 or abs(value - round(p)) < 0.005 for p in known_prices
        ):
            return False
    return True


class Judge:
    def __init__(self, llm: StructuredLLM, model: str) -> None:
        self._llm = llm
        self._model = model

    async def judge(
        self, request: str, plan: Plan, results: list[SiteResult]
    ) -> Verdict | None:
        best = choose_best(results)
        if best is None:
            return None
        best_site, offer = best
        facts = caveat_facts(results, best_site)
        summary = template_summary(best_site, offer, facts)

        data = {
            "request": request,
            "focus": plan.focus or None,
            "best": {
                "shop": best_site.site_name,
                "product": offer.name,
                "price": money(offer),
            },
            "caveats": facts,
        }
        try:
            narration = await self._llm.structured(
                model=self._model,
                system=SYSTEM,
                user=f"<facts>\n{json.dumps(data, ensure_ascii=False)}\n</facts>",
                schema=Narration,
                tool_name="write_summary",
                max_tokens=300,
            )
        except Exception as exc:  # noqa: BLE001  (API errors too: the template always works)
            log.warning("judge wording failed (%s); using the template", type(exc).__name__)
        else:
            if narration_ok(narration.summary, best_site, offer, results):
                summary = narration.summary
            else:
                log.warning("judge wording disagreed with the data; using the template")

        return Verdict(
            summary=summary,
            best_site_id=best_site.site_id,
            best_offer_name=offer.name,
            caveats="; ".join(facts)[:300],
        )

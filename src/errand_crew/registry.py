"""Site registry and the URL allowlist.

The allowlist is enforced in code (here, and again inside the cloud browser), never
only in a prompt. Users and models cannot supply URLs: every URL a worker visits is
built here from a registry template, and checked against the allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

DEFAULT_PATH = Path(__file__).with_name("sites.yaml")

# Hard cap on pages read per site, enforced in code whatever sites.yaml says.
MAX_PAGES = 3


@dataclass(frozen=True)
class Listing:
    """One category page of one site."""

    url: str
    sorted_by_price: bool = False  # True only where the cheapest-first URL was verified


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    domain: str
    categories: dict[str, Listing] = field(default_factory=dict)
    sort_asc: str | None = None  # template with {base}
    next_page: str | None = None  # template with {listing} and {n}
    max_pages: int = 1


def host_allowed(host: str, domain: str) -> bool:
    """True for the domain itself or any subdomain, never for look-alikes."""
    host = host.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


class Registry:
    def __init__(self, categories: dict[str, str], sites: list[Site]) -> None:
        self.categories = dict(categories)
        self._sites = {s.id: s for s in sites}
        if len(self._sites) != len(sites):
            raise ValueError("duplicate site id in registry")
        for site in sites:
            self._validate_site(site)

    def _validate_site(self, site: Site) -> None:
        if not 1 <= site.max_pages <= MAX_PAGES:
            raise ValueError(f"{site.id}: max_pages must be between 1 and {MAX_PAGES}")
        if site.max_pages > 1 and not site.next_page:
            raise ValueError(f"{site.id}: max_pages > 1 needs a next_page template")
        if site.sort_asc is not None and "{base}" not in site.sort_asc:
            raise ValueError(f"{site.id}: sort_asc must contain {{base}}")
        if site.next_page is not None and not (
            "{listing}" in site.next_page and "{n}" in site.next_page
        ):
            raise ValueError(f"{site.id}: next_page must contain {{listing}} and {{n}}")
        for cat, listing in site.categories.items():
            if cat not in self.categories:
                raise ValueError(f"{site.id}: unknown category {cat!r}")
            if listing.sorted_by_price and not site.sort_asc:
                raise ValueError(f"{site.id}/{cat}: sorted but the site has no sort_asc")
            # Every URL this site can ever be asked to open must pass the allowlist.
            for page in range(1, self.pages_for(site.id, cat) + 1):
                if self.page_url(site.id, cat, page) is None:
                    raise ValueError(f"{site.id}/{cat}: page {page} URL not allowed")

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "Registry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        sites = []
        for s in data["sites"]:
            cats: dict[str, Listing] = {}
            for cat, value in (s.get("categories") or {}).items():
                if isinstance(value, str):
                    cats[cat] = Listing(value)
                else:
                    cats[cat] = Listing(
                        value["url"], bool(value.get("sorted_by_price", False))
                    )
            sites.append(
                Site(
                    id=s["id"],
                    name=s["name"],
                    domain=s["domain"].lower(),
                    categories=cats,
                    sort_asc=s.get("sort_asc"),
                    next_page=s.get("next_page"),
                    max_pages=int(s.get("max_pages", 1)),
                )
            )
        return cls(data["categories"], sites)

    def site(self, site_id: str) -> Site | None:
        return self._sites.get(site_id)

    @property
    def domains(self) -> list[str]:
        return sorted({s.domain for s in self._sites.values()})

    def is_allowed_url(self, url: str) -> bool:
        """https only, an allowlisted host, no credentials in the URL, standard port."""
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            return False
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        if parts.scheme != "https" or not parts.hostname:
            return False
        if parts.username is not None or parts.password is not None:
            return False
        if port not in (None, 443):
            return False
        return any(host_allowed(parts.hostname, d) for d in self.domains)

    # --- categories, listings and pages -----------------------------------

    def sites_for(self, category: str) -> list[Site]:
        """Sites that have a verified listing URL for this category."""
        return [s for s in self._sites.values() if category in s.categories]

    def available_categories(self) -> dict[str, str]:
        """Categories at least one site can answer; the planner only sees these."""
        return {c: d for c, d in self.categories.items() if self.sites_for(c)}

    def listing(self, site_id: str, category: str) -> Listing | None:
        site = self.site(site_id)
        return site.categories.get(category) if site else None

    def pages_for(self, site_id: str, category: str) -> int:
        """How many pages a worker may read for this site and category (0 if unknown)."""
        site = self.site(site_id)
        if site is None or category not in site.categories:
            return 0
        return min(site.max_pages, MAX_PAGES) if site.next_page else 1

    def page_url(self, site_id: str, category: str, page: int) -> str | None:
        """URL of page `page` (1-based), or None if it does not exist or is not allowed."""
        site = self.site(site_id)
        listing = self.listing(site_id, category)
        if site is None or listing is None or isinstance(page, bool):
            return None
        if not isinstance(page, int) or not 1 <= page <= self.pages_for(site_id, category):
            return None
        first = listing.url
        if listing.sorted_by_price and site.sort_asc:
            first = site.sort_asc.replace("{base}", listing.url)
        if page == 1:
            url = first
        else:
            assert site.next_page is not None  # guaranteed by pages_for
            url = site.next_page.replace("{listing}", first).replace("{n}", str(page))
        return url if self.is_allowed_url(url) else None

    def url_for(self, site_id: str, category: str) -> str | None:
        """Page-1 URL (the cheapest-first version where verified)."""
        return self.page_url(site_id, category, 1)

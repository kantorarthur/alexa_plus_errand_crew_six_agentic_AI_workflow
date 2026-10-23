"""Errand lifecycle: plan, fan out workers in parallel, judge, store the result."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict

from .config import Settings
from .judge import NO_RESULT, Judge
from .planner import Planner
from .registry import Registry, Site
from .schemas import Errand, ErrandResult, Plan, SiteResult
from .security import SlidingWindowLimiter
from .workers import Worker

log = logging.getLogger(__name__)


class Busy(Exception):
    """Too many errands running at once."""


class RateLimited(Exception):
    """Hourly or daily errand budget used up."""


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        planner: Planner,
        worker: Worker,
        judge: Judge,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._planner = planner
        self._worker = worker
        self._judge = judge
        self._errands: OrderedDict[str, Errand] = OrderedDict()
        self._tasks: set[asyncio.Task] = set()
        self._active = 0
        self._hour = SlidingWindowLimiter(settings.max_errands_per_hour, 3600)
        self._day = SlidingWindowLimiter(settings.max_errands_per_day, 86400)

    # --- public API -------------------------------------------------------

    def start(self, request: str) -> Errand:
        if not (self._hour.check() and self._day.check()):
            raise RateLimited
        if self._active >= self._settings.max_concurrent_errands:
            raise Busy
        self._hour.record()
        self._day.record()

        errand = Errand(id=uuid.uuid4().hex, request=request)
        self._errands[errand.id] = errand
        self._evict()
        self._active += 1
        task = asyncio.create_task(self._run(errand))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return errand

    def get(self, errand_id: str) -> Errand | None:
        return self._errands.get(errand_id)

    async def wait_idle(self) -> None:
        """Wait for running errands (used by tests and graceful shutdown)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    # --- internals --------------------------------------------------------

    def _evict(self) -> None:
        finished = [i for i, e in self._errands.items() if e.state in ("done", "failed")]
        while len(self._errands) > self._settings.kept_errands and finished:
            self._errands.pop(finished.pop(0), None)

    async def _run(self, errand: Errand) -> None:
        try:
            errand.state = "planning"
            plan = await self._planner.plan(errand.request)
            errand.plan = plan

            if not plan.supported or not plan.category:
                self._finish(errand, plan, [], None, plan.reason or NO_RESULT)
                return

            sites = [s for i in plan.site_ids if (s := self._registry.site(i))]
            errand.state = "running"
            errand.progress = {s.id: "pending" for s in sites}
            results = await asyncio.gather(
                *(self._run_site(errand, s, plan.category, plan.focus) for s in sites)
            )

            errand.state = "judging"
            verdict = await self._judge.judge(errand.request, plan, list(results))
            spoken = verdict.summary if verdict else NO_RESULT
            self._finish(errand, plan, list(results), verdict, spoken)
        except Exception:  # noqa: BLE001
            log.exception("errand %s failed", errand.id)
            errand.state = "failed"
            errand.error = "Something went wrong while running this errand."
        finally:
            self._active -= 1

    async def _run_site(
        self, errand: Errand, site: Site, category: str, focus: str
    ) -> SiteResult:
        errand.progress[site.id] = "running"
        try:
            result = await asyncio.wait_for(
                self._worker.run(site, category, focus),
                timeout=self._settings.worker_timeout_s,
            )
        except asyncio.TimeoutError:
            result = SiteResult(
                site_id=site.id,
                site_name=site.name,
                source_url=self._registry.url_for(site.id, category) or "",
                status="error",
                error="timed out",
            )
        except Exception:  # noqa: BLE001
            log.exception("worker %s crashed", site.id)
            result = SiteResult(
                site_id=site.id,
                site_name=site.name,
                source_url="",
                status="error",
                error="worker failed",
            )
        errand.progress[site.id] = result.status
        return result

    @staticmethod
    def _finish(errand, plan: Plan, results, verdict, spoken: str) -> None:
        errand.result = ErrandResult(
            request=errand.request,
            plan=plan,
            sites=results,
            verdict=verdict,
            spoken_summary=spoken,
        )
        errand.state = "done"

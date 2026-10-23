import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from errand_crew.orchestrator import Busy, RateLimited
from errand_crew.registry import Registry
from errand_crew.security import BearerTokenVerifier
from errand_crew.server import build_server

from fakes import (
    TOKEN,
    FakeFetcher,
    FakeLLM,
    PageFetch,
    Plan,
    offer,
    Verdict,
    WorkerOutput,
    listing_text,
    make_orchestrator,
    make_settings,
)

REG = Registry.load()
EVO = REG.url_for("evomag", "laptops")
ALT = REG.url_for("altex", "laptops")


def happy_parts():
    pages = {
        EVO: PageFetch(200, EVO, listing_text(("Laptop ASUS Vivobook 15", "3.499,99"))),
        ALT: PageFetch(200, ALT, listing_text(("Laptop Lenovo IdeaPad 3", "2.899"))),
    }

    def worker_out(user: str):
        if "ASUS" in user:
            return WorkerOutput(offers=[offer("Laptop ASUS Vivobook 15", 3499.99)])
        return WorkerOutput(offers=[offer("Laptop Lenovo IdeaPad 3", 2899)])

    llm = FakeLLM(
        submit_plan=Plan(supported=True, category="laptops", site_ids=["evomag", "altex"], focus="cheap"),
        report_offers=worker_out,
        submit_verdict=Verdict(
            summary="The Lenovo IdeaPad 3 at altex.ro is cheapest.",
            best_site_id="altex",
            best_offer_name="Laptop Lenovo IdeaPad 3",
        ),
    )
    return llm, FakeFetcher(pages)


async def test_errand_end_to_end_runs_workers_in_parallel():
    llm, fetcher = happy_parts()
    orch = make_orchestrator(llm, fetcher)
    errand = orch.start("cheapest laptop")
    await orch.wait_idle()
    assert errand.state == "done"
    assert errand.progress == {"evomag": "ok", "altex": "ok"}
    assert errand.result.spoken_summary.startswith("The Lenovo")
    assert sorted(fetcher.fetched) == sorted([EVO, ALT])
    # Models are routed by role: workers never use the planner/judge model.
    assert {c["model"] for c in llm.calls if c["tool"] == "report_offers"} == {"worker-model"}


async def test_unsupported_request_finishes_politely():
    llm = FakeLLM(submit_plan=Plan(supported=False, reason="I only compare electronics."))
    orch = make_orchestrator(llm, FakeFetcher({}))
    errand = orch.start("book me a flight")
    await orch.wait_idle()
    assert errand.state == "done"
    assert errand.result.spoken_summary == "I only compare electronics."


async def test_no_offers_never_invents_a_price():
    llm, fetcher = happy_parts()
    llm.by_tool["report_offers"] = WorkerOutput()
    orch = make_orchestrator(llm, fetcher)
    errand = orch.start("cheapest laptop")
    await orch.wait_idle()
    assert errand.result.verdict is None
    assert "couldn't find" in errand.result.spoken_summary


async def test_one_worker_timeout_does_not_sink_the_errand():
    llm, fetcher = happy_parts()

    class SlowFetcher(FakeFetcher):
        async def fetch(self, url):
            if url == EVO:
                await asyncio.sleep(5)
            return await super().fetch(url)

        def open(self):
            ctx = super().open()
            outer = self

            class _Ctx:
                async def __aenter__(self_inner):
                    await ctx.__aenter__()
                    return outer

                async def __aexit__(self_inner, *exc):
                    return await ctx.__aexit__(*exc)

            return _Ctx()

    orch = make_orchestrator(llm, SlowFetcher(fetcher.pages), make_settings(worker_timeout_s=1))
    errand = orch.start("cheapest laptop")
    await orch.wait_idle()
    assert errand.state == "done"
    assert errand.progress["evomag"] == "error" and errand.progress["altex"] == "ok"


async def test_failure_does_not_leak_internals():
    llm = FakeLLM(submit_plan=RuntimeError("secret internal detail sk-123"))
    orch = make_orchestrator(llm, FakeFetcher({}))
    errand = orch.start("laptop")
    await orch.wait_idle()
    assert errand.state == "failed"
    assert "sk-123" not in errand.error


async def test_concurrency_cap_and_rate_limit():
    llm, fetcher = happy_parts()
    orch = make_orchestrator(llm, fetcher, make_settings(max_concurrent_errands=1))
    orch.start("laptop one")
    with pytest.raises(Busy):
        orch.start("laptop two")
    await orch.wait_idle()

    orch = make_orchestrator(llm, fetcher, make_settings(max_errands_per_hour=1))
    orch.start("laptop one")
    await orch.wait_idle()
    with pytest.raises(RateLimited):
        orch.start("laptop two")


async def test_mcp_tools_flow():
    llm, fetcher = happy_parts()
    orch = make_orchestrator(llm, fetcher)
    async with Client(build_server(orch)) as client:
        tools = {t.name for t in await client.list_tools()}
        assert tools == {"start_errand", "get_status", "get_result"}

        started = (await client.call_tool("start_errand", {"request": "cheapest laptop"})).data
        eid = started["errand_id"]
        await orch.wait_idle()

        status = (await client.call_tool("get_status", {"errand_id": eid})).data
        assert status["status"] == "done"
        result = (await client.call_tool("get_result", {"errand_id": eid})).data
        assert result["ready"] is True and "Lenovo" in result["spoken_summary"]


async def test_mcp_rejects_bad_ids_and_short_requests():
    llm, fetcher = happy_parts()
    async with Client(build_server(make_orchestrator(llm, fetcher))) as client:
        for bad in ("nope", "../../etc/passwd", "0" * 32):
            with pytest.raises(ToolError):
                await client.call_tool("get_status", {"errand_id": bad})
        with pytest.raises(ToolError):
            await client.call_tool("start_errand", {"request": "x"})


def test_http_endpoint_requires_bearer_token():
    from starlette.testclient import TestClient

    llm, fetcher = happy_parts()
    mcp = build_server(
        make_orchestrator(llm, fetcher), auth=BearerTokenVerifier({"demo": TOKEN})
    )
    app = mcp.http_app(path="/mcp")
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(app) as http:
        assert http.post("/mcp", json=body, headers=headers).status_code == 401
        bad = {**headers, "Authorization": "Bearer wrong"}
        assert http.post("/mcp", json=body, headers=bad).status_code == 401

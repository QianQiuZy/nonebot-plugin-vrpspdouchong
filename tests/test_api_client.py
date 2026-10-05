from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from time import monotonic

import httpx
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "vrpsp_api_client_tests", Path(__file__).resolve().parents[1] / "api_client.py"
)
assert _SPEC is not None and _SPEC.loader is not None
api_client = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(api_client)


@pytest.fixture(autouse=True)
def reset_limiter(monkeypatch):
    monkeypatch.setattr(api_client, "_limiter", api_client._RequestLimiter())


@pytest.fixture
def virtual_clock(monkeypatch):
    now = [100.0]
    delays = []

    async def sleep(delay):
        delays.append(delay)
        now[0] += delay

    monkeypatch.setattr(api_client, "monotonic", lambda: now[0])
    monkeypatch.setattr(api_client, "sleep", sleep)
    return now, delays


def test_concurrent_clients_and_hosts_share_15_tps_limit():
    starts = []

    def handler(request):
        starts.append(monotonic())
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as vr,
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as psp,
        ):
            responses = await asyncio.gather(*(
                api_client.get(
                    vr if index % 2 else psp,
                    f"https://{'vr' if index % 2 else 'psp'}.test/gift",
                )
                for index in range(31)
            ))
            assert all(response.status_code == 200 for response in responses)

    asyncio.run(run())

    assert len(starts) == 31
    assert all(later - earlier >= 1 / 15 - 0.001 for earlier, later in zip(starts, starts[1:]))
    assert all(sum(start <= other < start + 1 for other in starts) <= 15 for start in starts)


def test_429_waits_one_second_and_preserves_request_parameters(virtual_clock):
    now, delays = virtual_clock
    requests = []
    starts = []

    def handler(request):
        requests.append(str(request.url))
        starts.append(now[0])
        return httpx.Response(429 if len(requests) < 3 else 200, json={"attention": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await api_client.get(
                client, "https://vr.test/gift/attention", params={"room_id": "123"}
            )
            assert response.json() == {"attention": []}

    asyncio.run(run())

    assert requests == ["https://vr.test/gift/attention?room_id=123"] * 3
    assert starts == [100.0, 101.0, 102.0]
    assert delays == [1.0, 1.0]


def test_persistent_429_stops_after_three_retries(virtual_clock):
    _, delays = virtual_clock
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.HTTPStatusError) as error:
                await api_client.get(client, "https://vr.test/gift")
            assert error.value.response.status_code == 429

    asyncio.run(run())

    assert len(requests) == 4
    assert delays == [1.0, 1.0, 1.0]


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_other_http_errors_are_not_retried(status, virtual_clock):
    _, delays = virtual_clock
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await api_client.get(client, "https://vr.test/gift")

    asyncio.run(run())

    assert len(requests) == 1
    assert delays == []


def test_429_cooldown_also_delays_other_requests():
    starts = []
    rate_limited_at = []

    def handler(request):
        starts.append(monotonic())
        if not rate_limited_at:
            rate_limited_at.append(monotonic())
            return httpx.Response(429)
        return httpx.Response(200)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await asyncio.gather(
                api_client.get(client, "https://vr.test/gift"),
                api_client.get(client, "https://psp.test/gift"),
            )

    asyncio.run(run())

    assert len(starts) == 3
    assert starts[1] - rate_limited_at[0] >= 1.0
    assert starts[2] - starts[1] >= 1 / 15 - 0.001


def test_cancelling_queued_request_does_not_block_following_requests():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        ) as client:
            await api_client.get(client, "https://vr.test/gift")
            queued = asyncio.create_task(api_client.get(client, "https://vr.test/gift"))
            await asyncio.sleep(0)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
            response = await asyncio.wait_for(api_client.get(client, "https://vr.test/gift"), timeout=1)
            assert response.status_code == 200

    asyncio.run(run())

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import anyio
import httpx
import pytest
from nonebot.adapters.onebot.v11 import Message

from test_query_attention import query
from nonebot_plugin_vrpspdouchong.commands import douchong


EVENT = SimpleNamespace(user_id=1, group_id=2)


@pytest.mark.parametrize("year", ["0000", "2027", "２０２６"])
def test_rejects_invalid_annual_args(monkeypatch, year):
    monkeypatch.setattr(douchong, "current_month_code", lambda: "202601")
    assert douchong.normalize_period_arg(year) is None


@pytest.mark.parametrize("source", ["vr", "psp", "vup"])
@pytest.mark.parametrize("year", ["2026", "2025", "0001"])
def test_annual_command_fetches_one_year_per_source(monkeypatch, source, year):
    calls = []
    base = getattr(query.cfg, f"{source}_gift_api_base")
    row = {"anchor_name": "主播", "gift": 6.25, "live_duration": "100:01:02", "fans_count": None}

    async def get(_client, url, *, params):
        calls.append(httpx.Request("GET", url, params=params).url)
        return httpx.Response(200, json=[row])

    draw = Mock(return_value=["png"])
    send = AsyncMock()
    monkeypatch.setattr(douchong, "current_month_code", lambda: "202601")
    monkeypatch.setattr(douchong, "api_get", get)
    monkeypatch.setattr(douchong, "render_table_images", draw)
    monkeypatch.setattr(douchong, "send_douchong_images", send)

    async def run():
        return await douchong._handle_douchong(None, EVENT, Message(year), api_base=base, title=source)

    assert anyio.run(run) is None
    assert calls == [httpx.URL(f"{base}/by_month?year={year}")]
    assert draw.call_args.args[1] == [row]
    assert draw.call_args.kwargs == {"show_monthly_details": False, "show_live_status": False}
    send.assert_awaited_once()


def test_brawl_annual_requests_vr_and_psp_only(monkeypatch):
    calls = []

    async def get(_client, url, *, params):
        calls.append(httpx.Request("GET", url, params=params).url)
        return httpx.Response(200, json=[{"anchor_name": "主播", "gift": 4}])

    draw = Mock(return_value=["png"])
    monkeypatch.setattr(douchong, "current_month_code", lambda: "202601")
    monkeypatch.setattr(douchong, "api_get", get)
    monkeypatch.setattr(douchong, "render_table_images", draw)
    monkeypatch.setattr(douchong, "send_douchong_images", AsyncMock())

    assert anyio.run(douchong._handle_douchong_brawl, None, EVENT, Message("2026")) is None
    assert calls == [
        httpx.URL(f"{query.cfg.vr_gift_api_base}/by_month?year=2026"),
        httpx.URL(f"{query.cfg.psp_gift_api_base}/by_month?year=2026"),
    ]
    assert len(draw.call_args.args[1]) == 2
    assert draw.call_args.kwargs == {"show_monthly_details": False, "show_live_status": False}


@pytest.mark.parametrize("raw", ["", "2026-01", "202601"])
def test_monthly_request_still_uses_month(monkeypatch, raw):
    monkeypatch.setattr(douchong, "current_month_code", lambda: "202601")
    get = AsyncMock(return_value=httpx.Response(200, json=[]))
    monkeypatch.setattr(douchong, "api_get", get)

    assert anyio.run(douchong.fetch_period_data, "https://example.test/gift", douchong.normalize_period_arg(raw)) == []
    get.assert_awaited_once()
    assert get.call_args.args[1] == "https://example.test/gift/by_month"
    assert get.call_args.kwargs == {"params": {"month": "202601"}}


def test_annual_failure_does_not_fall_back_to_months(monkeypatch):
    calls = []

    async def get(_client, url, *, params):
        req = httpx.Request("GET", url, params=params)
        calls.append(req.url)
        httpx.Response(503, request=req).raise_for_status()

    monkeypatch.setattr(douchong, "current_month_code", lambda: "202601")
    monkeypatch.setattr(douchong, "api_get", get)

    async def run():
        return await douchong._handle_douchong(
            None, EVENT, Message("2026"), api_base="https://example.test/gift", title="VR斗虫",
        )

    result = anyio.run(run)
    assert result.type == "text" and "请求数据失败" in result.data["text"]
    assert calls == [httpx.URL("https://example.test/gift/by_month?year=2026")]


def test_dynamic_annual_duration_only_applies_to_live_rooms_this_year(monkeypatch):
    monkeypatch.setattr(douchong, "current_month_code", lambda: "202601")
    calc = Mock(return_value="101:00:00")
    monkeypatch.setattr(douchong, "calc_live_duration_with_live_time", calc)
    rows = [
        {"status": 0, "live_duration": "100:00:00", "live_time": "2026-01-01 00:00:00"},
        {"status": 1, "live_duration": "100:00:00", "live_time": "2026-01-01 00:00:00"},
    ]

    douchong.update_period_live_duration(rows, douchong.normalize_period_arg("2025"))
    calc.assert_not_called()
    douchong.update_period_live_duration(rows, douchong.normalize_period_arg("2026"))

    calc.assert_called_once()
    assert [row["live_duration"] for row in rows] == ["100:00:00", "101:00:00"]

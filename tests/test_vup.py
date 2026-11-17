from itertools import product
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import httpx
import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.rule import CommandRule

# Reuse the repository's local-package loader.
from test_query_attention import query
from nonebot_plugin_vrpspdouchong.commands import douchong, live_list

VUP_BASE = "https://vup.qianqiuzy.cn/gift"
EVENT = SimpleNamespace(user_id=1, group_id=2)


@pytest.mark.parametrize("module,command", [(douchong, "斗虫"), (live_list, "开播")])
def test_vup_command_accepts_every_case_combination(module, command):
    matcher = getattr(module, "VUP" + command)
    rules = [checker.call for checker in matcher.rule.checkers if isinstance(checker.call, CommandRule)]
    assert len(rules) == 1
    for letters in product(*[(c.lower(), c.upper()) for c in "vup"]):
        assert anyio.run(rules[0], ("".join(letters) + command,), Message(), None)


def test_vup_douchong_handler_routes_to_configured_source(monkeypatch):
    handler = AsyncMock(return_value=MessageSegment.text("result"))
    finish = AsyncMock()
    monkeypatch.setattr(douchong, "_handle_douchong", handler)
    monkeypatch.setattr(douchong, "finish_message", finish)
    anyio.run(douchong.VUP斗虫.handlers[0].call, None, EVENT, Message("202611"))
    assert handler.call_args.kwargs == {
        "api_base": VUP_BASE, "title": "VUP斗虫",
    }
    assert finish.call_args.args[0] is douchong.VUP斗虫


def test_vup_live_handler_routes_to_configured_source(monkeypatch):
    handler = AsyncMock(return_value=MessageSegment.text("result"))
    finish = AsyncMock()
    monkeypatch.setattr(live_list, "_handle_live_list", handler)
    monkeypatch.setattr(live_list, "finish_message", finish)
    anyio.run(live_list.VUP开播.handlers[0].call, EVENT)
    assert handler.call_args.kwargs["api_url"] == VUP_BASE
    assert handler.call_args.kwargs["title"] == "VUP开播"
    assert finish.call_args.args[0] is live_list.VUP开播


@pytest.mark.parametrize("period", ["", "202611", "2026-11", "2025", "20261106"])
def test_vup_douchong_supports_existing_periods(monkeypatch, period):
    fetch = AsyncMock(return_value=[{"room_id": 263605, "anchor_name": "小缘"}])
    daily = AsyncMock(return_value="png")
    monkeypatch.setattr(douchong, "fetch_period_data", fetch)
    monkeypatch.setattr(douchong, "build_daily_image", daily)
    monkeypatch.setattr(douchong, "render_table_images", lambda *a, **k: ["png"])
    monkeypatch.setattr(douchong, "send_douchong_images", AsyncMock())

    async def run():
        return await douchong._handle_douchong(
            None, EVENT, Message(period), api_base=VUP_BASE, title="VUP斗虫"
        )

    anyio.run(run)
    if period == "20261106":
        assert daily.call_args.kwargs["api_base"] == VUP_BASE
        assert daily.call_args.kwargs["day_code"] == period
        fetch.assert_not_awaited()
    else:
        assert fetch.call_args.args[0] == VUP_BASE
        if period == "2025":
            assert fetch.call_args.args[1] == douchong.QueryPeriod("2025", "2025年 1-12月累计", annual=True)
        daily.assert_not_awaited()


@pytest.mark.parametrize("vr_fails", [False, True])
def test_anchor_search_reaches_vup_when_earlier_sources_do_not_match(monkeypatch, vr_fails):
    calls = []
    row = {"room_id": 263605, "anchor_name": "小缘"}

    async def fetch(url):
        calls.append(url)
        if vr_fails and url == query.cfg.vr_gift_api_base:
            raise RuntimeError("unavailable")
        return [row] if url == VUP_BASE else []

    monkeypatch.setattr(query, "_fetch_json", fetch)
    assert anyio.run(query._locate_room_by_anchor, "小缘") == (VUP_BASE, row)
    assert calls == [query.cfg.vr_gift_api_base, query.cfg.psp_gift_api_base, VUP_BASE]


def test_anchor_search_preserves_vr_priority(monkeypatch):
    fetch = AsyncMock(return_value=[{"room_id": 1, "anchor_name": "重叠主播"}])
    monkeypatch.setattr(query, "_fetch_json", fetch)
    assert anyio.run(query._locate_room_by_anchor, "重叠")[0] == query.cfg.vr_gift_api_base
    fetch.assert_awaited_once_with(query.cfg.vr_gift_api_base)


def test_monthly_query_includes_vup_and_deduplicates_shared_rooms(monkeypatch):
    calls = []
    shared = {"room_id": 1, "anchor_name": "重复主播"}
    vup = {"room_id": 263605, "anchor_name": "小缘"}

    async def get(client, url, *, params):
        calls.append(url)
        assert params == {"month": "202611"}
        return httpx.Response(200, json=[shared, vup] if url.startswith(VUP_BASE) else [shared])

    monkeypatch.setattr(query, "api_get", get)
    assert anyio.run(query.fetch_all_data_by_month, "202611") == [shared, vup]
    assert set(calls) == {
        f"{base}/by_month" for base in
        (query.cfg.vr_gift_api_base, query.cfg.psp_gift_api_base, VUP_BASE)
    }


@pytest.mark.parametrize("period", ["202611", "20261106"])
def test_brawl_douchong_remains_vr_psp_only(monkeypatch, period):
    calls = []

    async def fetch(base, period):
        calls.append(base)
        return [{"room_id": len(calls), "anchor_name": "主播"}]

    daily = AsyncMock(return_value="png")
    monkeypatch.setattr(douchong, "fetch_period_data", fetch)
    monkeypatch.setattr(douchong, "build_brawl_daily_image", daily)
    monkeypatch.setattr(douchong, "render_table_images", lambda *a, **k: ["png"])
    monkeypatch.setattr(douchong, "send_douchong_images", AsyncMock())
    anyio.run(douchong._handle_douchong_brawl, None, EVENT, Message(period))
    if period == "20261106":
        assert daily.call_args.kwargs["vr_api_base"] == douchong.cfg.vr_gift_api_base
        assert daily.call_args.kwargs["psp_api_base"] == douchong.cfg.psp_gift_api_base
        assert VUP_BASE not in daily.call_args.kwargs.values()
    else:
        assert calls == [douchong.cfg.vr_gift_api_base, douchong.cfg.psp_gift_api_base]


def test_brawl_live_list_remains_vr_psp_only(monkeypatch):
    calls = []

    async def fetch(url):
        calls.append(url)
        return [{"status": 1, "anchor_name": "主播"}]

    monkeypatch.setattr(live_list, "_fetch_json_list", fetch)
    monkeypatch.setattr(live_list, "finish_message", AsyncMock())
    monkeypatch.setattr(live_list, "_render_live_list_image", lambda *a: "png")
    anyio.run(live_list.大乱斗开播.handlers[0].call, EVENT)
    assert set(calls) == {live_list.cfg.vr_gift_api_base, live_list.cfg.psp_gift_api_base}

from __future__ import annotations

import base64
import importlib.util
import io
import sys
from pathlib import Path

import anyio
import httpx
import nonebot
from PIL import Image

nonebot.init()

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_NAME = "nonebot_plugin_vrpspdouchong"
_PACKAGE_SPEC = importlib.util.spec_from_file_location(
    _PACKAGE_NAME,
    _PACKAGE_ROOT / "__init__.py",
    submodule_search_locations=[str(_PACKAGE_ROOT)],
)
assert _PACKAGE_SPEC is not None and _PACKAGE_SPEC.loader is not None
_PACKAGE = importlib.util.module_from_spec(_PACKAGE_SPEC)
sys.modules[_PACKAGE_NAME] = _PACKAGE
_PACKAGE_SPEC.loader.exec_module(_PACKAGE)

from nonebot_plugin_vrpspdouchong.commands.douchong_daily import (
    DAILY_HEADERS,
    build_daily_row,
    fetch_daily_data,
    normalize_day_arg,
    render_daily_table_image,
)


def test_normalize_day_arg_accepts_calendar_date() -> None:
    assert normalize_day_arg("20260913") == "20260913"
    assert normalize_day_arg("20260931") is None
    assert normalize_day_arg("2026-09-13") is None


def test_build_daily_row_uses_the_requested_attention_record() -> None:
    room = {"room_id": 1820703922, "anchor_name": "花礼Harei"}
    payload = {
        "attention": [
            {"date": "20260912", "gift": 100, "guard": 200, "super_chat": 300},
            {"date": "20260913", "gift": 4387.54, "guard": 25716, "super_chat": 490},
        ]
    }

    row = build_daily_row(room, payload, "20260913")

    assert row is not None
    assert row.anchor_name == "花礼Harei"
    assert row.gift == 4387.54
    assert row.guard == 25716.0
    assert row.super_chat == 490.0
    assert row.total == 30593.54


def test_fetch_daily_data_traverses_rooms_and_filters_the_day() -> None:
    responses = {
        "https://example.test/gift": httpx.Response(
            200,
            json=[
                {"room_id": 1, "anchor_name": "主播A"},
                {"room_id": 2, "anchor_name": "主播B"},
            ],
        ),
        "https://example.test/gift/attention?room_id=1": httpx.Response(
            200,
            json={"attention": [{"date": "20260913", "gift": 1, "guard": 2, "super_chat": 3}]},
        ),
        "https://example.test/gift/attention?room_id=2": httpx.Response(
            200,
            json={"attention": [{"date": "20260912", "gift": 10, "guard": 20, "super_chat": 30}]},
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses.get(str(request.url))
        assert response is not None
        return response

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            rows = await fetch_daily_data(client, "https://example.test/gift", "20260913")
        assert [(row.room_id, row.anchor_name) for row in rows] == [("1", "主播A")]

    anyio.run(run)


def test_render_daily_table_has_only_the_five_requested_columns() -> None:
    image_b64 = render_daily_table_image(
        title="VR斗虫",
        day_code="20260913",
        rows=[build_daily_row(
            {"room_id": 1, "anchor_name": "主播A"},
            {"attention": [{"date": "20260913", "gift": 1, "guard": 2, "super_chat": 3}]},
            "20260913",
        )],
        query_source_text="测试查询",
    )

    image = Image.open(io.BytesIO(base64.b64decode(image_b64)))
    assert DAILY_HEADERS == ("主播名称", "舰长", "SC", "礼物", "总计")
    assert image.width == 1320

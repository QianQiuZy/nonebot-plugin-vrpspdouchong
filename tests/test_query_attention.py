from __future__ import annotations

import base64
import importlib
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

query = importlib.import_module(f"{_PACKAGE_NAME}.commands.query")
_attention_delta = getattr(query, "_attention_delta")
_format_attention_count = getattr(query, "_format_attention_count")
_format_fans_count = getattr(query, "_format_fans_count")
_format_guard_count = getattr(query, "_format_guard_count")


def _row(date: str, attention: int | None) -> tuple[str, int | None, None, None, None, None, None, None]:
    return date, attention, None, None, None, None, None, None


def test_attention_zero_or_null_renders_as_unavailable() -> None:
    assert _format_attention_count(None) == "-"
    assert _format_attention_count(0) == "-"
    assert _format_attention_count(12) == "12"


def test_guard_only_null_renders_as_unavailable() -> None:
    assert _format_guard_count(None) == "-"
    assert _format_guard_count(0) == "0"
    assert _format_guard_count(12) == "12"


def test_fans_count_null_renders_as_unavailable() -> None:
    assert _format_fans_count(None) == "-"
    assert _format_fans_count(0) == "0"
    assert _format_fans_count(12) == "12"


def test_attention_delta_ignores_zero_and_null_snapshots() -> None:
    rows = [
        _row("20260901", 100),
        _row("20260902", None),
        _row("20260903", 0),
        _row("20260904", 150),
    ]

    assert _attention_delta(rows) == 50
    assert _attention_delta([_row("20260901", None), _row("20260902", 0)]) == 0


def test_query_keeps_unavailable_attention_rows_for_dash_rendering(monkeypatch) -> None:
    async def fake_fetch(_url: str) -> dict[str, list[dict[str, int | str | None]]]:
        return {
            "attention": [
                {"date": "20260919", "attention": "148431", "guard_1": 200},
                {"date": "20260920", "attention": "0", "guard_1": None},
                {"date": "20260921", "attention": None, "guard_1": 0},
            ],
        }

    monkeypatch.setattr(query, "_fetch_json", fake_fetch)

    async def run() -> list[tuple[str, int | None, None, None, None, None, None, None]]:
        return await query.query_attention_snapshots(
            base="https://example.test/gift",
            room_id="1820703922",
            month_code="202609",
        )

    rows = anyio.run(run)

    assert [row[1] for row in rows] == [148431, 0, None]


def test_attention_image_footer_stays_inside_opaque_canvas() -> None:
    image_b64 = query.render_attention_image(
        anchor_name="主播A",
        room_id="1820703922",
        month_code="202609",
        attention_rows=[_row("20260901", 100), _row("20260902", 120)],
        query_source_text="测试",
    )
    image = Image.open(io.BytesIO(base64.b64decode(image_b64)))
    bottom_strip = image.crop((0, image.height - 10, image.width, image.height))

    assert bottom_strip.getextrema() == ((255, 255), (255, 255), (255, 255), (255, 255))


def test_month_list_keeps_data_after_429_retry(monkeypatch) -> None:
    from nonebot_plugin_vrpspdouchong import api_client

    monkeypatch.setattr(api_client, "_limiter", api_client._RequestLimiter())
    attempts = []
    expected = [{"room_id": 1, "anchor_name": "主播A"}]

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(str(request.url))
        return httpx.Response(429 if len(attempts) == 1 else 200, json=expected)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            rows = await query._fetch_month_list(client, "https://example.test/gift", "202609")
        assert rows == expected

    anyio.run(run)

    assert attempts == ["https://example.test/gift/by_month?month=202609"] * 2

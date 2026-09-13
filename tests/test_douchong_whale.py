from __future__ import annotations

import base64
import importlib.util
import io
import sys
from pathlib import Path

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

from nonebot_plugin_vrpspdouchong.commands import douchong
from nonebot_plugin_vrpspdouchong.commands.douchong import (
    format_whale_ratio,
    has_whale_dependency_data,
    render_table_image,
)


def _row(whale_dependency: object) -> dict[str, object]:
    return {
        "anchor_name": "主播A",
        "gift": 1,
        "guard": 2,
        "super_chat": 3,
        "live_duration": "01:00:00",
        "whale_dependency": whale_dependency,
    }


def test_whale_ratio_is_percentage_with_one_decimal_place() -> None:
    assert format_whale_ratio(0.0461009658865671) == "4.6%"
    assert format_whale_ratio(None) == "-"


def test_unavailable_whale_dependency_hides_columns() -> None:
    assert not has_whale_dependency_data([_row({"status": "unavailable"})])
    assert has_whale_dependency_data([_row({"status": "live"})])


def test_monthly_render_adds_whale_columns_only_when_enabled() -> None:
    row = _row(
        {
            "status": "live",
            "top1": 0.0461009658865671,
            "top5": 0.2,
            "top10": 0.3,
            "top1_percent": 0.04,
        }
    )
    without_whales = Image.open(
        io.BytesIO(
            base64.b64decode(
                render_table_image("VR斗虫", [dict(row)], "2026-09", "测试", False)
            )
        )
    )
    with_whales = Image.open(
        io.BytesIO(
            base64.b64decode(
                render_table_image("VR斗虫", [dict(row)], "2026-09", "测试", True)
            )
        )
    )
    assert with_whales.width == without_whales.width + 440


def test_monthly_header_places_payer_count_after_guard_amount(monkeypatch) -> None:
    drawn_texts: list[str] = []

    class Recorder:
        def __init__(self, *args, **kwargs):
            pass

        def set_pos(self, *args, **kwargs):
            return self

        def draw_rounded_rectangle(self, *args, **kwargs):
            return self

        def draw_text(self, text, *args, **kwargs):
            if isinstance(text, str):
                drawn_texts.append(text)
            return self

        def draw_text_right(self, *args, **kwargs):
            return self

        def crop_and_paste_bottom(self):
            return self

        def base64(self):
            return "test"

    monkeypatch.setattr(douchong, "PicGenerator", Recorder)
    douchong.render_table_image("VR斗虫", [_row({"status": "unavailable"})], "2026-09", "测试")

    assert drawn_texts.index("上舰") < drawn_texts.index("月付费数")

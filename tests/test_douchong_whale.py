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

douchong = importlib.import_module(f"{_PACKAGE_NAME}.commands.douchong")
_douchong_table = importlib.import_module(f"{_PACKAGE_NAME}.commands.douchong_table")
PRIMARY_TABLE_HEADERS = getattr(_douchong_table, "PRIMARY_TABLE_HEADERS")
build_primary_total_row = getattr(_douchong_table, "build_primary_total_row")
build_primary_headers = getattr(_douchong_table, "build_primary_headers")
build_secondary_headers = getattr(_douchong_table, "build_secondary_headers")
format_danmaku_ratio = getattr(_douchong_table, "format_danmaku_ratio")
format_whale_ratio = getattr(_douchong_table, "format_whale_ratio")
has_danmaku_role_data = getattr(_douchong_table, "has_danmaku_role_data")
has_danmaku_data = getattr(_douchong_table, "has_danmaku_data")
has_whale_dependency_data = getattr(_douchong_table, "has_whale_dependency_data")
render_table_images = getattr(_douchong_table, "render_table_images")


def _row(
    whale_dependency: object,
    danmaku: object | None = None,
) -> dict[str, object]:
    return {
        "anchor_name": "主播A",
        "gift": 1,
        "guard": 2,
        "super_chat": 3,
        "live_duration": "01:00:00",
        "guard_1": 1,
        "guard_2": 2,
        "guard_3": 3,
        "whale_dependency": whale_dependency,
        "danmaku": danmaku,
    }


def test_whale_ratio_is_percentage_with_one_decimal_place() -> None:
    assert format_whale_ratio(0.0461009658865671) == "4.6%"
    assert format_whale_ratio(None) == "-"


def test_unavailable_whale_dependency_hides_columns() -> None:
    assert not has_whale_dependency_data([_row({"status": "unavailable"})])
    assert has_whale_dependency_data([_row({"status": "live"})])


def test_danmaku_ratio_uses_total_and_one_decimal_place() -> None:
    assert format_danmaku_ratio(231, 1000) == "23.1%"
    assert format_danmaku_ratio(None, 1000) == "-"
    assert format_danmaku_ratio(0, 0) == "0.0%"


def test_all_null_role_counts_hide_only_the_four_role_columns() -> None:
    row = _row(
        {"status": "unavailable"},
        {
            "total": 100,
            "normal": None,
            "captain": None,
            "admiral": None,
            "governor": None,
        },
    )

    assert has_danmaku_data([row])
    assert not has_danmaku_role_data([row])
    assert build_secondary_headers([row], show_monthly_details=True) == (
        "主播名称",
        "舰长",
        "提督",
        "总督",
        "粉丝团",
        "月付费数",
        "弹幕总数",
    )


def test_monthly_secondary_headers_include_whales_and_role_ratios() -> None:
    row = _row(
        {"status": "live"},
        {"total": 100, "normal": 70, "captain": 20, "admiral": 8, "governor": 2},
    )

    assert build_secondary_headers([row], show_monthly_details=True) == (
        "主播名称",
        "舰长",
        "提督",
        "总督",
        "粉丝团",
        "月付费数",
        "top1",
        "top5",
        "top10",
        "top1%",
        "弹幕总数",
        "普通弹幕",
        "舰长弹幕",
        "提督弹幕",
        "总督弹幕",
    )


def test_null_guard_counts_hide_their_columns_independently() -> None:
    row = _row(
        {"status": "unavailable"},
        {"total": 100, "normal": None, "captain": None, "admiral": None, "governor": None},
    )
    row["guard_1"] = None
    row["guard_3"] = None

    headers = build_secondary_headers([row], show_monthly_details=True)
    images = render_table_images(
        "VR斗虫",
        [dict(row)],
        "2026-09",
        "测试",
        show_monthly_details=True,
    )

    assert headers == (
        "主播名称",
        "提督",
        "粉丝团",
        "月付费数",
        "弹幕总数",
    )
    assert len(images) == 2
    secondary = Image.open(io.BytesIO(base64.b64decode(images[1])))
    assert secondary.width == 830


def test_all_null_danmaku_fields_are_unavailable() -> None:
    row = _row(
        {"status": "unavailable"},
        {"total": None, "normal": None, "captain": None, "admiral": None, "governor": None},
    )

    assert not has_danmaku_data([row])


def test_annual_period_stays_annual_when_january_has_only_one_month(monkeypatch) -> None:
    monkeypatch.setattr(douchong, "build_year_month_codes", lambda year: [f"{year}01"])

    period = douchong.normalize_period_arg("2026")

    assert period == (["202601"], "2026年 1-1月累计", False)


def test_live_status_is_only_enabled_for_the_current_month(monkeypatch) -> None:
    monkeypatch.setattr(douchong, "current_month_code", lambda: "202609")

    assert douchong.should_show_live_status(["202609"])
    assert not douchong.should_show_live_status(["202608"])
    assert not douchong.should_show_live_status(["202609", "202608"])


def test_historical_primary_headers_and_image_hide_live_status() -> None:
    row = _row({"status": "unavailable"}, {"total": None})

    images = render_table_images(
        "VR斗虫",
        [dict(row)],
        "2026-08",
        "测试",
        show_monthly_details=True,
        show_live_status=False,
    )

    assert build_primary_headers(show_live_status=False) == (
        "主播名称",
        "总计",
        "粉丝数",
        "直播时间",
        "时薪",
        "有效天",
        "盲盒数",
        "盲盒盈亏",
        "礼物",
        "SC",
        "上舰",
    )
    assert len(images) == 1
    assert Image.open(io.BytesIO(base64.b64decode(images[0]))).width == 1950


def test_monthly_render_splits_the_requested_columns_into_two_images() -> None:
    row = _row(
        {
            "status": "live",
            "top1": 0.0461009658865671,
            "top5": 0.2,
            "top10": 0.3,
            "top1_percent": 0.04,
        },
        {"total": 100, "normal": 70, "captain": 20, "admiral": 8, "governor": 2},
    )
    images = render_table_images(
        "VR斗虫",
        [dict(row)],
        "2026-09",
        "测试",
        show_monthly_details=True,
    )

    decoded = [Image.open(io.BytesIO(base64.b64decode(image))) for image in images]
    assert PRIMARY_TABLE_HEADERS == (
        "主播名称",
        "总计",
        "粉丝数",
        "直播状态",
        "直播时间",
        "时薪",
        "有效天",
        "盲盒数",
        "盲盒盈亏",
        "礼物",
        "SC",
        "上舰",
    )
    assert len(decoded) == 2
    assert decoded[0].width == 2100
    assert decoded[1].width == 2010
    for image in decoded:
        bottom_strip = image.crop((0, image.height - 10, image.width, image.height))
        assert bottom_strip.getextrema() == ((255, 255), (255, 255), (255, 255), (255, 255))


def test_primary_image_keeps_the_existing_total_values() -> None:
    total_row = build_primary_total_row(
        [_row({"status": "unavailable"})],
    )

    assert total_row == (
        "合计",
        "6.0",
        "",
        "",
        "1.0小时",
        "6.00",
        "",
        "0",
        "0.0",
        "1.0",
        "3.0",
        "2.0",
    )


def test_monthly_render_returns_only_primary_when_detail_sources_are_unavailable() -> None:
    row = _row(
        {
            "status": "unavailable",
            "top1": None,
            "top5": None,
            "top10": None,
            "top1_percent": None,
        },
        {"total": None, "normal": None, "captain": None, "admiral": None, "governor": None},
    )
    row["guard_1"] = None
    row["guard_2"] = None
    row["guard_3"] = None

    images = render_table_images(
        "VR斗虫",
        [dict(row)],
        "2026-08",
        "测试",
        show_monthly_details=True,
    )

    assert len(images) == 1


def test_annual_render_returns_only_primary_even_when_detail_sources_are_available() -> None:
    row = _row(
        {"status": "live", "top1": 0.1, "top5": 0.2, "top10": 0.3, "top1_percent": 0.04},
        {"total": 100, "normal": 70, "captain": 20, "admiral": 8, "governor": 2},
    )

    images = render_table_images(
        "VR斗虫",
        [dict(row)],
        "2026年 1-9月累计",
        "测试",
        show_monthly_details=False,
        show_live_status=False,
    )

    assert len(images) == 1
    assert Image.open(io.BytesIO(base64.b64decode(images[0]))).width == 1950

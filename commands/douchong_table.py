from __future__ import annotations

import time
from typing import Any, Final

from ..toolkit import Color, PicGenerator, timestamp_format

Cell = tuple[str, Color]

PRIMARY_TABLE_HEADERS: Final = (
    "主播名称", "总计", "粉丝数", "直播状态", "直播时间", "时薪", "有效天",
    "盲盒数", "盲盒盈亏", "礼物", "SC", "上舰", "月付费数",
)
_PRIMARY_WIDTHS: Final = (300, 220, 140, 150, 200, 180, 100, 100, 130, 180, 180, 180, 140)
_SECONDARY_BASE_HEADERS: Final = ("主播名称", "舰长", "提督", "总督", "粉丝团", "月付费数")
_SECONDARY_BASE_WIDTHS: Final = (300, 90, 90, 90, 120, 140)
_WHALE_HEADERS: Final = ("top1", "top5", "top10", "top1%")
_WHALE_WIDTHS: Final = (110, 110, 110, 110)
_DANMAKU_ROLE_HEADERS: Final = ("普通弹幕", "舰长弹幕", "提督弹幕", "总督弹幕")
_DANMAKU_ROLE_FIELDS: Final = ("normal", "captain", "admiral", "governor")
_DANMAKU_ROLE_WIDTHS: Final = (140, 140, 140, 140)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _duration_to_seconds(hms: Any) -> int:
    try:
        parts = str(hms).split(":")
        if len(parts) != 3:
            return 0
        hours, minutes, seconds = map(int, parts)
        return max(0, hours * 3600 + minutes * 60 + seconds)
    except (TypeError, ValueError):
        return 0


def _seconds_to_duration(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remainder = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remainder:02d}"


def format_duration(hms: Any) -> str:
    seconds = _duration_to_seconds(hms)
    if seconds == 0 and str(hms) not in {"00:00:00", "0:00:00"}:
        return str(hms)
    return f"{seconds / 3600:.1f}小时"


def format_fans(attention: int) -> str:
    return f"{attention / 10000:.1f}万" if attention >= 10000 else str(attention)


def format_count(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "-"


def format_hourly_rate(total: Any, live_duration: Any) -> str:
    duration_seconds = _duration_to_seconds(live_duration)
    if duration_seconds <= 0:
        return "0.00"
    return f"{_to_float(total) / (duration_seconds / 3600):.2f}"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _whale_dependency(row: dict[str, Any]) -> dict[str, Any]:
    return _mapping(row.get("whale_dependency"))


def _danmaku(row: dict[str, Any]) -> dict[str, Any]:
    return _mapping(row.get("danmaku"))


def has_whale_dependency_data(data_list: list[dict[str, Any]]) -> bool:
    return any(_whale_dependency(row).get("status") in {"live", "archived", "partial"} for row in data_list)


def has_danmaku_role_data(data_list: list[dict[str, Any]]) -> bool:
    return any(
        any(_danmaku(row).get(field) is not None for field in _DANMAKU_ROLE_FIELDS)
        for row in data_list
    )


def format_whale_ratio(value: Any) -> str:
    return "-" if value is None else f"{_to_float(value) * 100:.1f}%"


def format_danmaku_ratio(value: Any, total: Any) -> str:
    if value is None:
        return "-"
    total_count = _to_int(total)
    if total_count <= 0:
        return "0.0%"
    return f"{_to_int(value) / total_count * 100:.1f}%"


def build_secondary_headers(
    data_list: list[dict[str, Any]],
    *,
    show_monthly_details: bool,
) -> tuple[str, ...]:
    headers: list[str] = list(_SECONDARY_BASE_HEADERS)
    if not show_monthly_details:
        return tuple(headers)
    if has_whale_dependency_data(data_list):
        headers.extend(_WHALE_HEADERS)
    headers.append("弹幕总数")
    if has_danmaku_role_data(data_list):
        headers.extend(_DANMAKU_ROLE_HEADERS)
    return tuple(headers)


def _prepared_rows(data_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for source in data_list:
        row = dict(source)
        row["total"] = sum(_to_float(row.get(field)) for field in ("gift", "super_chat", "guard"))
        row["duration_fmt"] = format_duration(row.get("live_duration", "00:00:00"))
        row["fans_fmt"] = format_fans(_to_int(row.get("attention")))
        prepared.append(row)
    return sorted(prepared, key=lambda row: _to_float(row.get("total")), reverse=True)


def build_primary_total_row(data_list: list[dict[str, Any]]) -> tuple[str, ...]:
    total_seconds = sum(_duration_to_seconds(row.get("live_duration", "00:00:00")) for row in data_list)
    total_box_count = sum(_to_int(row.get("blind_box_count")) for row in data_list)
    total_box_profit = sum(_to_float(row.get("blind_box_profit")) for row in data_list)
    total_gift = sum(_to_float(row.get("gift")) for row in data_list)
    total_sc = sum(_to_float(row.get("super_chat")) for row in data_list)
    total_guard = sum(_to_float(row.get("guard")) for row in data_list)
    total = total_gift + total_sc + total_guard
    duration = _seconds_to_duration(total_seconds)
    return (
        "合计", f"{total:.1f}", "", "", format_duration(duration), format_hourly_rate(total, duration), "",
        str(total_box_count), f"{total_box_profit:.1f}", f"{total_gift:.1f}", f"{total_sc:.1f}",
        f"{total_guard:.1f}", "",
    )


def _primary_rows(data_list: list[dict[str, Any]]) -> list[list[Cell]]:
    rows: list[list[Cell]] = []
    for row in data_list:
        is_live = _to_int(row.get("status")) == 1
        rows.append([
            (str(row.get("anchor_name", "")), Color.BLACK),
            (f"{_to_float(row.get('total')):.1f}", Color.BLACK),
            (str(row.get("fans_fmt", "0")), Color.BLACK),
            ("直播中" if is_live else "未开播", Color.DEEPSKYBLUE if is_live else Color.BLACK),
            (str(row.get("duration_fmt", "")), Color.BLACK),
            (format_hourly_rate(row.get("total"), row.get("live_duration")), Color.BLACK),
            (str(row.get("effective_days", "")), Color.BLACK),
            (format_count(row.get("blind_box_count")), Color.BLACK),
            (f"{_to_float(row.get('blind_box_profit')):.1f}", Color.BLACK),
            (f"{_to_float(row.get('gift')):.1f}", Color.BLACK),
            (f"{_to_float(row.get('super_chat')):.1f}", Color.BLACK),
            (f"{_to_float(row.get('guard')):.1f}", Color.BLACK),
            (str(_to_int(row.get("payer_count"))), Color.BLACK),
        ])
    return rows


def _secondary_rows(
    data_list: list[dict[str, Any]],
    *,
    show_whales: bool,
    show_danmaku_roles: bool,
    show_monthly_details: bool,
) -> list[list[Cell]]:
    rows: list[list[Cell]] = []
    for row in data_list:
        cells = [
            str(row.get("anchor_name", "")), format_count(row.get("guard_1")), format_count(row.get("guard_2")),
            format_count(row.get("guard_3")), format_count(row.get("fans_count")), str(_to_int(row.get("payer_count"))),
        ]
        if show_whales:
            whale = _whale_dependency(row)
            cells.extend(format_whale_ratio(whale.get(field)) for field in ("top1", "top5", "top10", "top1_percent"))
        if show_monthly_details:
            danmaku = _danmaku(row)
            cells.append(format_count(danmaku.get("total")))
            if show_danmaku_roles:
                cells.extend(format_danmaku_ratio(danmaku.get(field), danmaku.get("total")) for field in _DANMAKU_ROLE_FIELDS)
        rows.append([(cell, Color.BLACK) for cell in cells])
    return rows


def _render_image(
    title: str,
    period_display: str,
    query_source_text: str,
    headers: tuple[str, ...],
    widths: tuple[int, ...],
    rows: list[list[Cell]],
    total_row: tuple[str, ...] | None,
) -> str:
    row_height = 60
    table_width = sum(widths) + 40
    table_rows = 1 + len(rows) + (1 if total_row is not None else 0)
    canvas_height = row_height * table_rows + 250
    pic = PicGenerator(table_width, canvas_height)
    pic.set_pos(0, 0).draw_rounded_rectangle(0, 0, table_width, canvas_height, 0, Color.WHITE)
    pic.set_pos(20, 30).draw_text(title, [Color.BLACK])
    now = timestamp_format(int(time.time()), "%Y-%m-%d %H:%M:%S")
    pic.set_pos(20, 90).draw_text(now, [Color.GRAY])
    pic.set_pos(320, 90).draw_text("数据为每月1号开始统计，月底清零。", [Color.GRAY])
    pic.set_pos(20, 120).draw_text(query_source_text, [Color.GRAY])
    pic.set_pos(20, 150).draw_text(f"统计周期：{period_display}", [Color.GRAY])
    current_y = 190
    pic.draw_rounded_rectangle(20, current_y, table_width - 40, row_height, 0, Color.DEEPSKYBLUE)
    current_x = 30
    for width, header in zip(widths, headers):
        pic.set_pos(current_x, current_y + 18).draw_text(header, [Color.WHITE])
        current_x += width
    current_y += row_height
    for index, row in enumerate(rows):
        background = Color.LIGHTGRAY if index % 2 == 0 else Color.WHITE
        pic.draw_rounded_rectangle(20, current_y, table_width - 40, row_height, 0, background)
        current_x = 30
        for width, (text, color) in zip(widths, row):
            pic.set_pos(current_x, current_y + 18).draw_text(text, [color])
            current_x += width
        current_y += row_height
    if total_row is not None:
        pic.draw_rounded_rectangle(20, current_y, table_width - 40, row_height, 0, Color.LIGHTGRAY)
        current_x = 30
        for width, text in zip(widths, total_row):
            pic.set_pos(current_x, current_y + 18).draw_text(text, [Color.BLACK])
            current_x += width
    pic.set_pos(table_width - 220, canvas_height - 60).draw_text_right(0, "Designed by 开发猫", Color.GRAY)
    return pic.base64()


def render_table_images(
    title: str,
    data_list: list[dict[str, Any]],
    period_display: str,
    query_source_text: str,
    *,
    show_monthly_details: bool,
) -> list[str]:
    prepared = _prepared_rows(data_list)
    show_whales = show_monthly_details and has_whale_dependency_data(prepared)
    show_danmaku_roles = show_monthly_details and has_danmaku_role_data(prepared)
    secondary_headers = build_secondary_headers(prepared, show_monthly_details=show_monthly_details)
    secondary_widths: list[int] = list(_SECONDARY_BASE_WIDTHS)
    if show_whales:
        secondary_widths.extend(_WHALE_WIDTHS)
    if show_monthly_details:
        secondary_widths.append(140)
        if show_danmaku_roles:
            secondary_widths.extend(_DANMAKU_ROLE_WIDTHS)
    return [
        _render_image(
            f"{title}（流水概览）", period_display, query_source_text, PRIMARY_TABLE_HEADERS, _PRIMARY_WIDTHS,
            _primary_rows(prepared), build_primary_total_row(prepared),
        ),
        _render_image(
            f"{title}（用户结构）", period_display, query_source_text, secondary_headers, tuple(secondary_widths),
            _secondary_rows(
                prepared,
                show_whales=show_whales,
                show_danmaku_roles=show_danmaku_roles,
                show_monthly_details=show_monthly_details,
            ),
            None,
        ),
    ]

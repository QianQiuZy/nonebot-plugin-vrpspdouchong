from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from ..toolkit import Color
from .table_render import Cell, TableRender, render_table_image

PRIMARY_TABLE_HEADERS: Final = (
    "主播名称", "总计", "粉丝数", "直播状态", "直播时间", "时薪", "有效天",
    "盲盒数", "盲盒盈亏", "礼物", "SC", "上舰",
)
_PRIMARY_WIDTHS: Final = (300, 220, 140, 150, 200, 180, 100, 100, 130, 180, 180, 180)
_GUARD_COLUMNS: Final = (("guard_1", "舰长", 90), ("guard_2", "提督", 90), ("guard_3", "总督", 90))
_SECONDARY_FIXED_HEADERS: Final = ("粉丝团", "月付费数")
_SECONDARY_FIXED_WIDTHS: Final = (120, 140)
_WHALE_HEADERS: Final = ("top1", "top5", "top10", "top1%")
_WHALE_WIDTHS: Final = (110, 110, 110, 110)
_DANMAKU_ROLE_HEADERS: Final = ("普通弹幕", "舰长弹幕", "提督弹幕", "总督弹幕")
_DANMAKU_ROLE_FIELDS: Final = ("normal", "captain", "admiral", "governor")
_DANMAKU_FIELDS: Final = ("total", *_DANMAKU_ROLE_FIELDS)
_DANMAKU_ROLE_WIDTHS: Final = (140, 140, 140, 140)


@dataclass(frozen=True, slots=True)
class _SecondaryLayout:
    guard_fields: tuple[str, ...]
    show_whales: bool
    show_danmaku: bool
    show_danmaku_roles: bool


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


def build_primary_headers(*, show_live_status: bool = True) -> tuple[str, ...]:
    if show_live_status:
        return PRIMARY_TABLE_HEADERS
    return PRIMARY_TABLE_HEADERS[:3] + PRIMARY_TABLE_HEADERS[4:]


def _primary_widths(*, show_live_status: bool) -> tuple[int, ...]:
    if show_live_status:
        return _PRIMARY_WIDTHS
    return _PRIMARY_WIDTHS[:3] + _PRIMARY_WIDTHS[4:]


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _whale_dependency(row: dict[str, Any]) -> dict[str, Any]:
    return _mapping(row.get("whale_dependency"))


def _danmaku(row: dict[str, Any]) -> dict[str, Any]:
    return _mapping(row.get("danmaku"))


def has_whale_dependency_data(data_list: list[dict[str, Any]]) -> bool:
    return any(_whale_dependency(row).get("status") in {"live", "archived", "partial"} for row in data_list)


def has_danmaku_data(data_list: list[dict[str, Any]]) -> bool:
    return any(any(_danmaku(row).get(field) is not None for field in _DANMAKU_FIELDS) for row in data_list)


def has_danmaku_role_data(data_list: list[dict[str, Any]]) -> bool:
    return any(
        any(_danmaku(row).get(field) is not None for field in _DANMAKU_ROLE_FIELDS)
        for row in data_list
    )


def _visible_guard_fields(data_list: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        field
        for field, _header, _width in _GUARD_COLUMNS
        if any(row.get(field) is not None for row in data_list)
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
    guard_fields = _visible_guard_fields(data_list)
    headers = ["主播名称"]
    headers.extend(header for field, header, _width in _GUARD_COLUMNS if field in guard_fields)
    headers.extend(_SECONDARY_FIXED_HEADERS)
    if not show_monthly_details:
        return tuple(headers)
    if has_whale_dependency_data(data_list):
        headers.extend(_WHALE_HEADERS)
    if has_danmaku_data(data_list):
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


def build_primary_total_row(
    data_list: list[dict[str, Any]],
    *,
    show_live_status: bool = True,
) -> tuple[str, ...]:
    total_seconds = sum(_duration_to_seconds(row.get("live_duration", "00:00:00")) for row in data_list)
    total_box_count = sum(_to_int(row.get("blind_box_count")) for row in data_list)
    total_box_profit = sum(_to_float(row.get("blind_box_profit")) for row in data_list)
    total_gift = sum(_to_float(row.get("gift")) for row in data_list)
    total_sc = sum(_to_float(row.get("super_chat")) for row in data_list)
    total_guard = sum(_to_float(row.get("guard")) for row in data_list)
    total = total_gift + total_sc + total_guard
    duration = _seconds_to_duration(total_seconds)
    cells = ["合计", f"{total:.1f}", ""]
    if show_live_status:
        cells.append("")
    cells.extend([
        format_duration(duration),
        format_hourly_rate(total, duration),
        "",
        str(total_box_count),
        f"{total_box_profit:.1f}",
        f"{total_gift:.1f}",
        f"{total_sc:.1f}",
        f"{total_guard:.1f}",
    ])
    return tuple(cells)


def _primary_rows(
    data_list: list[dict[str, Any]],
    *,
    show_live_status: bool,
) -> list[list[Cell]]:
    rows: list[list[Cell]] = []
    for row in data_list:
        is_live = _to_int(row.get("status")) == 1
        cells: list[Cell] = [
            (str(row.get("anchor_name", "")), Color.BLACK),
            (f"{_to_float(row.get('total')):.1f}", Color.BLACK),
            (str(row.get("fans_fmt", "0")), Color.BLACK),
        ]
        if show_live_status:
            cells.append(("直播中" if is_live else "未开播", Color.DEEPSKYBLUE if is_live else Color.BLACK))
        cells.extend([
            (str(row.get("duration_fmt", "")), Color.BLACK),
            (format_hourly_rate(row.get("total"), row.get("live_duration")), Color.BLACK),
            (str(row.get("effective_days", "")), Color.BLACK),
            (format_count(row.get("blind_box_count")), Color.BLACK),
            (f"{_to_float(row.get('blind_box_profit')):.1f}", Color.BLACK),
            (f"{_to_float(row.get('gift')):.1f}", Color.BLACK),
            (f"{_to_float(row.get('super_chat')):.1f}", Color.BLACK),
            (f"{_to_float(row.get('guard')):.1f}", Color.BLACK),
        ])
        rows.append(cells)
    return rows


def _secondary_rows(
    data_list: list[dict[str, Any]],
    layout: _SecondaryLayout,
) -> list[list[Cell]]:
    rows: list[list[Cell]] = []
    for row in data_list:
        cells = [str(row.get("anchor_name", ""))]
        cells.extend(format_count(row.get(field)) for field in layout.guard_fields)
        cells.extend((format_count(row.get("fans_count")), str(_to_int(row.get("payer_count")))))
        if layout.show_whales:
            whale = _whale_dependency(row)
            cells.extend(format_whale_ratio(whale.get(field)) for field in ("top1", "top5", "top10", "top1_percent"))
        if layout.show_danmaku:
            danmaku = _danmaku(row)
            cells.append(format_count(danmaku.get("total")))
            if layout.show_danmaku_roles:
                cells.extend(format_danmaku_ratio(danmaku.get(field), danmaku.get("total")) for field in _DANMAKU_ROLE_FIELDS)
        rows.append([(cell, Color.BLACK) for cell in cells])
    return rows


def render_table_images(
    title: str,
    data_list: list[dict[str, Any]],
    period_display: str,
    query_source_text: str,
    *,
    show_monthly_details: bool,
    show_live_status: bool = True,
) -> list[str]:
    prepared = _prepared_rows(data_list)
    primary_image = render_table_image(TableRender(
        title=f"{title}（流水概览）",
        period_display=period_display,
        query_source_text=query_source_text,
        headers=build_primary_headers(show_live_status=show_live_status),
        widths=_primary_widths(show_live_status=show_live_status),
        rows=_primary_rows(prepared, show_live_status=show_live_status),
        total_row=build_primary_total_row(prepared, show_live_status=show_live_status),
    ))
    if not show_monthly_details:
        return [primary_image]

    show_whales = has_whale_dependency_data(prepared)
    show_danmaku = has_danmaku_data(prepared)
    if not show_whales and not show_danmaku:
        return [primary_image]

    guard_fields = _visible_guard_fields(prepared)
    show_danmaku_roles = has_danmaku_role_data(prepared)
    layout = _SecondaryLayout(guard_fields, show_whales, show_danmaku, show_danmaku_roles)
    secondary_headers = build_secondary_headers(prepared, show_monthly_details=show_monthly_details)
    secondary_widths = [300]
    secondary_widths.extend(width for field, _header, width in _GUARD_COLUMNS if field in guard_fields)
    secondary_widths.extend(_SECONDARY_FIXED_WIDTHS)
    if show_whales:
        secondary_widths.extend(_WHALE_WIDTHS)
    if show_danmaku:
        secondary_widths.append(140)
        if show_danmaku_roles:
            secondary_widths.extend(_DANMAKU_ROLE_WIDTHS)
    return [
        primary_image,
        render_table_image(TableRender(
            title=f"{title}（用户结构）",
            period_display=period_display,
            query_source_text=query_source_text,
            headers=secondary_headers,
            widths=tuple(secondary_widths),
            rows=_secondary_rows(prepared, layout),
            total_row=None,
        )),
    ]

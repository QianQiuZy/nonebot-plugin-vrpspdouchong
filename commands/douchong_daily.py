from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

import anyio
import httpx

from ..api_client import get as api_get
from ..toolkit import Color, PicGenerator, timestamp_format

DAILY_HEADERS: Final = ("主播名称", "舰长", "SC", "礼物", "总计")
_DAILY_COL_WIDTHS: Final = (480, 200, 200, 200, 200)
_DAY_RE: Final = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


@dataclass(frozen=True, slots=True)
class DailyGiftRow:
    """One room's gift totals for one calendar day."""

    room_id: str
    anchor_name: str
    guard: float
    super_chat: float
    gift: float
    total: float


def normalize_day_arg(raw: str) -> str | None:
    """Return a valid YYYYMMDD argument, or None for a non-day argument."""
    text = raw.strip()
    match = _DAY_RE.fullmatch(text)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    if not 1 <= month <= 12:
        return None
    try:
        date(year, month, day)
    except ValueError:
        return None
    return text


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _room_id(room: Mapping[str, Any]) -> str:
    return str(room.get("room_id") or "").strip()


def _room_list(payload: Any) -> list[dict[str, Any]]:
    items = payload if isinstance(payload, list) else payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise TypeError("接口返回异常：/gift 不是房间列表")
    return [item for item in items if isinstance(item, dict) and _room_id(item)]


def _attention_items(payload: Any) -> list[dict[str, Any]]:
    items = payload.get("attention") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def build_daily_row(
    room: Mapping[str, Any],
    payload: Any,
    day_code: str,
) -> DailyGiftRow | None:
    """Parse the attention response row matching ``day_code``."""
    record = next(
        (item for item in _attention_items(payload) if str(item.get("date") or "") == day_code),
        None,
    )
    room_id = _room_id(room)
    if record is None or not room_id:
        return None

    guard = _to_float(record.get("guard"))
    super_chat = _to_float(record.get("super_chat"))
    gift = _to_float(record.get("gift"))
    return DailyGiftRow(
        room_id=room_id,
        anchor_name=str(room.get("anchor_name") or room_id),
        guard=guard,
        super_chat=super_chat,
        gift=gift,
        total=guard + super_chat + gift,
    )


async def _fetch_daily_row(
    client: httpx.AsyncClient,
    api_base: str,
    room: dict[str, Any],
    day_code: str,
    limiter: anyio.CapacityLimiter,
) -> DailyGiftRow | None:
    async with limiter:
        response = await api_get(client, f"{api_base}/attention", params={"room_id": _room_id(room)})
    return build_daily_row(room, response.json(), day_code)


async def fetch_daily_data(
    client: httpx.AsyncClient,
    api_base: str,
    day_code: str,
) -> list[DailyGiftRow]:
    """Traverse /gift and collect matching /attention records for one day."""
    response = await api_get(client, api_base)
    rooms = _room_list(response.json())
    rows: list[DailyGiftRow] = []
    limiter = anyio.CapacityLimiter(10)

    async def collect(room: dict[str, Any]) -> None:
        try:
            row = await _fetch_daily_row(client, api_base, room, day_code, limiter)
        except (httpx.HTTPError, ValueError):
            return
        if row is not None:
            rows.append(row)

    async with anyio.create_task_group() as task_group:
        for room in rooms:
            task_group.start_soon(collect, room)

    return sorted(rows, key=lambda row: row.total, reverse=True)


def render_daily_table_image(
    *,
    title: str,
    day_code: str,
    rows: Sequence[DailyGiftRow | None],
    query_source_text: str,
) -> str:
    """Render the daily ranking using exactly the five requested columns."""
    valid_rows = [row for row in rows if row is not None]
    valid_rows.sort(key=lambda row: row.total, reverse=True)
    table_width = sum(_DAILY_COL_WIDTHS) + 40
    row_height = 60
    header_height = 190
    table_height = row_height * (max(1, len(valid_rows)) + 2) + 40
    canvas_height = header_height + table_height

    pic = PicGenerator(table_width, canvas_height)
    pic.set_pos(0, 0).draw_rounded_rectangle(0, 0, table_width, canvas_height, 0, Color.WHITE)
    day_display = f"{day_code[:4]}-{day_code[4:6]}-{day_code[6:]}"
    pic.set_pos(20, 30).draw_text(f"{title} {day_display}", Color.BLACK)
    pic.set_pos(20, 90).draw_text(query_source_text, Color.GRAY)
    pic.set_pos(20, 120).draw_text(
        f"查询时间：{timestamp_format(int(time.time()), '%Y-%m-%d %H:%M:%S')}",
        Color.GRAY,
    )

    origin_x = 20
    cur_y = header_height
    pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, Color.DEEPSKYBLUE)
    cur_x = origin_x + 10
    for width, header in zip(_DAILY_COL_WIDTHS, DAILY_HEADERS):
        pic.set_pos(cur_x, cur_y + 18).draw_text(header, Color.WHITE)
        cur_x += width
    cur_y += row_height

    totals = [0.0, 0.0, 0.0]
    for index, row in enumerate(valid_rows):
        totals[0] += row.guard
        totals[1] += row.super_chat
        totals[2] += row.gift
        background = Color.LIGHTGRAY if index % 2 == 0 else Color.WHITE
        pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, background)
        cells = [row.anchor_name, f"{row.guard:.1f}", f"{row.super_chat:.1f}", f"{row.gift:.1f}", f"{row.total:.1f}"]
        cur_x = origin_x + 10
        for width, cell in zip(_DAILY_COL_WIDTHS, cells):
            pic.set_pos(cur_x, cur_y + 18).draw_text(cell, Color.BLACK)
            cur_x += width
        cur_y += row_height

    total_sum = sum(totals)
    pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, Color.LIGHTGRAY)
    total_cells = ["合计", f"{totals[0]:.1f}", f"{totals[1]:.1f}", f"{totals[2]:.1f}", f"{total_sum:.1f}"]
    cur_x = origin_x + 10
    for width, cell in zip(_DAILY_COL_WIDTHS, total_cells):
        pic.set_pos(cur_x, cur_y + 18).draw_text(cell, Color.BLACK)
        cur_x += width

    pic.set_pos(table_width - 220, canvas_height - 40).draw_text_right(0, "Designed by 开发猫", Color.GRAY)
    pic.crop_and_paste_bottom()
    return pic.base64()


async def build_daily_image(
    *,
    api_base: str,
    day_code: str,
    title: str,
    query_source_text: str,
    timeout: float,
) -> str | None:
    """Fetch and render one platform's daily ranking."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        rows = await fetch_daily_data(client, api_base, day_code)
    if not rows:
        return None
    return render_daily_table_image(
        title=title,
        day_code=day_code,
        rows=rows,
        query_source_text=query_source_text,
    )


async def build_brawl_daily_image(
    *,
    vr_api_base: str,
    psp_api_base: str,
    day_code: str,
    title: str,
    query_source_text: str,
    timeout: float,
) -> str | None:
    """Fetch both platforms and render one combined daily ranking."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        vr_rows = await fetch_daily_data(client, vr_api_base, day_code)
        psp_rows = await fetch_daily_data(client, psp_api_base, day_code)
    rows = vr_rows + psp_rows
    if not rows:
        return None
    return render_daily_table_image(
        title=title,
        day_code=day_code,
        rows=rows,
        query_source_text=query_source_text,
    )

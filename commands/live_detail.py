from __future__ import annotations

import datetime
import time
from pathlib import Path
from typing import Any

import httpx
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.params import CommandArg

from ..toolkit import Color, PicGenerator, timestamp_format
from .query import (
    _locate_room_by_anchor,
    _parse_anchor_and_month,
    _save_sc_image_file,
    _sc_image_uri,
    _send_forward_images,
    build_query_source_text,
    query_live_sessions,
)

查直播详细 = on_command("查直播详细", block=True, priority=5)
_CHINA_TIMEZONE = datetime.timezone(datetime.timedelta(hours=8))


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_datetime(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(f"{value} +0800", "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def _format_duration(session: dict[str, Any]) -> str:
    start = _parse_datetime(str(session.get("start_time") or ""))
    end = _parse_datetime(str(session.get("end_time") or ""))
    if start is None:
        return "00:00:00"
    end_value = end or datetime.datetime.now(_CHINA_TIMEZONE)
    total_seconds = max(0, int((end_value - start).total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _format_optional_count(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(_to_int(value))


def _format_stat_time(value: Any) -> str:
    text = str(value or "")
    return text or "-"


def _session_stats(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw_stats = session.get("stats_15m")
    if not isinstance(raw_stats, list):
        return []
    stats = [item for item in raw_stats if isinstance(item, dict)]
    return sorted(stats, key=lambda item: _to_int(item.get("bucket_index")))


def _render_session_detail_image(
    *,
    anchor_name: str,
    room_id: str,
    month_code: str,
    session: dict[str, Any],
    session_index: int,
    total_sessions: int,
    query_source_text: str,
) -> str:
    stats = _session_stats(session)
    row_height = 60
    header_h = 250
    table_header_h = 60
    col_widths = [100, 340, 340, 140, 140, 140, 120, 160, 120, 160, 160, 160, 160]
    headers = [
        "区间", "开始时间", "结束时间", "礼物", "舰长", "SC", "盲盒数",
        "盲盒盈亏", "弹幕数", "平均同接", "最高同接", "采样次数", "付费人数",
    ]

    data_rows = max(1, len(stats))
    table_width = sum(col_widths) + 40
    table_height = table_header_h + row_height * data_rows + 40
    canvas_width = table_width
    canvas_height = header_h + table_height
    pic = PicGenerator(canvas_width, canvas_height)
    pic.set_pos(0, 0).draw_rounded_rectangle(0, 0, canvas_width, canvas_height, 0, Color.WHITE)

    start_time = str(session.get("start_time") or "-")
    end_time = str(session.get("end_time") or "直播中")
    title = str(session.get("title") or "-")
    month_display = f"{month_code[:4]}-{month_code[4:]}" if len(month_code) == 6 else month_code
    pic.set_pos(20, 30).draw_text(
        f"{anchor_name} 直播详细（第 {session_index}/{total_sessions} 场）",
        [Color.BLACK],
    )
    pic.set_pos(20, 90).draw_text(f"房间号：{room_id}    统计月份：{month_display}", [Color.GRAY])
    pic.set_pos(20, 120).draw_text(f"开播：{start_time}    下播：{end_time}", [Color.GRAY])
    pic.set_pos(20, 150).draw_text(f"时长：{_format_duration(session)}    标题：{title}", [Color.GRAY])
    pic.set_pos(20, 180).draw_text(
        f"{query_source_text}    查询时间：{timestamp_format(int(time.time()), '%Y-%m-%d %H:%M:%S')}",
        [Color.GRAY],
    )

    origin_x = 20
    cur_y = header_h
    pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, table_header_h, 0, Color.DEEPSKYBLUE)
    cur_x = origin_x + 10
    for width, header in zip(col_widths, headers):
        pic.set_pos(cur_x, cur_y + 18).draw_text(header, [Color.WHITE])
        cur_x += width
    cur_y += table_header_h

    if stats:
        for index, stat in enumerate(stats):
            background = Color.LIGHTGRAY if index % 2 == 0 else Color.WHITE
            pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, background)
            cells = [
                str(_to_int(stat.get("bucket_index"))),
                _format_stat_time(stat.get("start_time")),
                _format_stat_time(stat.get("end_time")),
                f"{_to_float(stat.get('gift')):.1f}",
                f"{_to_float(stat.get('guard')):.1f}",
                f"{_to_float(stat.get('super_chat')):.1f}",
                str(_to_int(stat.get("blind_box_count"))),
                f"{_to_float(stat.get('blind_box_profit')):.1f}",
                str(_to_int(stat.get("danmaku_count"))),
                _format_optional_count(stat.get("avg_concurrency")),
                _format_optional_count(stat.get("max_concurrency")),
                str(_to_int(stat.get("sample_count"))),
                str(_to_int(stat.get("payer_count"))),
            ]
            cur_x = origin_x + 10
            for width, cell in zip(col_widths, cells):
                pic.set_pos(cur_x, cur_y + 18).draw_text(cell, [Color.BLACK])
                cur_x += width
            cur_y += row_height
    else:
        pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, Color.WHITE)
        pic.set_pos(origin_x + 10, cur_y + 18).draw_text("（本场暂无 stats_15m 数据）", [Color.BLACK])

    pic.set_pos(canvas_width - 220, canvas_height - 40)
    pic.draw_text_right(0, "Designed by 开发猫", Color.GRAY)
    pic.crop_and_paste_bottom()
    return pic.base64()


def render_live_detail_images(
    *,
    anchor_name: str,
    room_id: str,
    month_code: str,
    sessions: list[dict[str, Any]],
    query_source_text: str,
) -> list[Path]:
    total_sessions = len(sessions)
    image_paths: list[Path] = []
    for session_index, session in enumerate(sessions, start=1):
        image_b64 = _render_session_detail_image(
            anchor_name=anchor_name,
            room_id=room_id,
            month_code=month_code,
            session=session,
            session_index=session_index,
            total_sessions=total_sessions,
            query_source_text=query_source_text,
        )
        image_paths.append(
            _save_sc_image_file(
                image_b64,
                anchor_name=anchor_name,
                page_no=session_index,
                total_pages=total_sessions,
            )
        )
    return image_paths


@查直播详细.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):  # noqa: B008
    anchor_kw, month_code = _parse_anchor_and_month(str(arg))
    if not anchor_kw:
        await 查直播详细.finish(MessageSegment.text("用法：/查直播详细 主播名称 [YYYYMM|YYYY-MM]"))
        return

    query_source_text = build_query_source_text(event)
    logger.info(f"[查直播详细] kw={anchor_kw} month={month_code} user={getattr(event, 'user_id', 0)}")
    base, match = await _locate_room_by_anchor(anchor_kw)
    if not base or not match:
        await 查直播详细.finish(MessageSegment.text("未找到用户"))
        return

    anchor_name = str(match.get("anchor_name") or anchor_kw)
    room_id = str(match.get("room_id") or "")
    if not room_id:
        await 查直播详细.finish(MessageSegment.text("该用户缺少房间信息"))
        return

    try:
        sessions = await query_live_sessions(base=base, room_id=room_id, month_code=month_code)
    except (httpx.HTTPError, ValueError) as error:
        await 查直播详细.finish(MessageSegment.text(f"未能获取直播场次：{error}"))
        return

    if not sessions:
        await 查直播详细.finish(MessageSegment.text("该主播本月暂无直播场次"))

    try:
        image_paths = render_live_detail_images(
            anchor_name=anchor_name,
            room_id=room_id,
            month_code=month_code,
            sessions=sessions,
            query_source_text=query_source_text,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        logger.exception("render_live_detail_images failed")
        await 查直播详细.finish(MessageSegment.text(f"生成图片失败：{error}"))
        return

    if len(image_paths) == 1:
        await 查直播详细.finish(MessageSegment.image(_sc_image_uri(image_paths[0])))

    await _send_forward_images(
        bot,
        event,
        title="查直播详细",
        image_paths=image_paths,
        anchor_name=anchor_name,
        item_label="场",
    )
    await 查直播详细.finish()

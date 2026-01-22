# src/plugins/douchong/commands/live_list.py
from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List

import httpx
from nonebot import get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import MessageSegment, MessageEvent
from nonebot.log import logger

from ..config import Config
from ..toolkit import PicGenerator, Color, timestamp_format

cfg = get_plugin_config(Config)

# VR开播：支持 /VR开播 /vr开播
VR开播 = on_command(
    "VR开播",
    aliases={"vr开播"},
    block=True,
    priority=5,
)

# PSP开播：支持 /PSP开播 /psp开播
PSP开播 = on_command(
    "PSP开播",
    aliases={"psp开播"},
    block=True,
    priority=5,
)


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _safe_str(v: Any) -> str:
    return "" if v is None else str(v)


def _calc_live_duration_hms(live_time_str: str) -> str:
    """
    live_time: "YYYY-MM-DD HH:MM:SS"
    失败则回退 "00:00:00"
    """
    try:
        start_dt = datetime.datetime.strptime(live_time_str, "%Y-%m-%d %H:%M:%S")
        now_dt = datetime.datetime.now()
        delta = now_dt - start_dt
        total_seconds = max(0, int(delta.total_seconds()))
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    except Exception:
        return "00:00:00"


def _limit_text_by_px(pic: PicGenerator, text: str, max_px: int) -> str:
    """
    按像素宽度裁剪，避免标题溢出（依赖 toolkit 的 fallback 量宽逻辑）
    """
    text = _safe_str(text)
    if not text:
        return ""

    # 允许调用内部量宽（你当前 toolkit 已实现）
    measure = getattr(pic, "_measure_with_fallback", None)
    if not callable(measure):
        return text  # 无量宽能力就不裁剪

    if measure(text) <= max_px:
        return text

    suffix = "..."
    suf_w = measure(suffix)
    # 逐字裁剪（标题一般不长；性能足够）
    acc = []
    for ch in text:
        acc.append(ch)
        if measure("".join(acc)) + suf_w > max_px:
            acc.pop()
            break
    return "".join(acc) + suffix


async def _fetch_json_list(url: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=cfg.vr_http_timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, list):
        raise ValueError("接口返回异常：非列表结构")
    return [d for d in data if isinstance(d, dict)]


def _render_live_list_image(title: str, live_list: List[Dict[str, Any]]) -> str:
    """
    表头：title + 当前时间
    列：开播时间、主播名称、已开播时长、直播标题
    排序：live_time 降序（已在上层处理）
    """
    # ---------- 表格参数 ----------
    row_height = 60
    col_widths = [350, 300, 200, 600]
    headers = ["开播时间", "主播名称", "已开播时长", "直播标题"]

    table_width = sum(col_widths) + 40
    table_height = row_height * (len(live_list) + 1) + 40
    canvas_width = table_width
    canvas_height = table_height + 140

    pic = PicGenerator(canvas_width, canvas_height)
    pic.set_pos(0, 0).draw_rounded_rectangle(0, 0, canvas_width, canvas_height, 35, Color.WHITE)

    # ---------- 标题与时间 ----------
    LEFT_PADDING = 20
    TITLE_Y = 30
    TIME_Y = 90
    TIP_X_OFFSET = 300

    pic.set_pos(LEFT_PADDING, TITLE_Y).draw_text(title, [Color.BLACK])
    now_str = timestamp_format(int(time.time()), "%Y-%m-%d %H:%M:%S")
    pic.set_pos(LEFT_PADDING, TIME_Y).draw_text(now_str, [Color.GRAY])
    pic.set_pos(LEFT_PADDING + TIP_X_OFFSET, TIME_Y).draw_text("仅列出当前正在直播的房间", [Color.GRAY])

    # ---------- 表格绘制 ----------
    origin_x = 20
    origin_y = 140
    cur_y = origin_y

    # 表头背景
    pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 12, Color.DEEPSKYBLUE)

    # 表头文字
    cur_x = origin_x + 10
    for w, h in zip(col_widths, headers):
        pic.set_pos(cur_x, cur_y + 18).draw_text(h, [Color.WHITE])
        cur_x += w

    # 表体
    cur_y += row_height
    for idx, d in enumerate(live_list):
        bg = Color.LIGHTGRAY if (idx % 2 == 0) else Color.WHITE
        pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, bg)

        live_time_val = _safe_str(d.get("live_time", "0000-00-00 00:00:00"))
        anchor_name = _safe_str(d.get("anchor_name", ""))
        duration_val = _calc_live_duration_hms(live_time_val)
        live_title = _safe_str(d.get("title", ""))

        # 裁剪直播标题以避免溢出（最大宽度=最后一列宽度-少量 padding）
        live_title = _limit_text_by_px(pic, live_title, max_px=col_widths[3] - 20)

        cur_x = origin_x + 10
        pic.set_pos(cur_x, cur_y + 18).draw_text(live_time_val, [Color.BLACK])
        cur_x += col_widths[0]

        pic.set_pos(cur_x, cur_y + 18).draw_text(anchor_name, [Color.BLACK])
        cur_x += col_widths[1]

        pic.set_pos(cur_x, cur_y + 18).draw_text(duration_val, [Color.BLACK])
        cur_x += col_widths[2]

        pic.set_pos(cur_x, cur_y + 18).draw_text(live_title, [Color.BLACK])

        cur_y += row_height

    # 版权
    pic.set_pos(canvas_width - 220, canvas_height - 40)
    pic.draw_text_right(0, "Designed by QianQiuZy", Color.GRAY)

    pic.crop_and_paste_bottom()
    return pic.base64()


async def _handle_live_list(*, api_url: str, title: str, user_id: int) -> MessageSegment:
    logger.info(f"[{title}] user={user_id}")

    try:
        data_list = await _fetch_json_list(api_url)
    except Exception as e:
        return MessageSegment.text(f"请求数据失败：{e}")

    # status == 1 表示直播中
    live_list = [d for d in data_list if _to_int(d.get("status", 0)) == 1]

    if not live_list:
        return MessageSegment.text("当前没有主播正在直播。")

    # live_time 越新越靠前（字符串降序即可）
    live_list.sort(key=lambda d: _safe_str(d.get("live_time", "")), reverse=True)

    try:
        b64 = _render_live_list_image(title, live_list)
    except Exception as e:
        logger.exception("render_live_list_image failed")
        return MessageSegment.text(f"生成图片失败：{e}")

    return MessageSegment.image(f"base64://{b64}")


@VR开播.handle()
async def _(event: MessageEvent):
    seg = await _handle_live_list(
        api_url=cfg.vr_gift_api_base,   # 直接请求 /gift（该值本身就是 https://vr.qianqiuzy.cn/gift）
        title=cfg.vr_live_title,
        user_id=getattr(event, "user_id", 0),
    )
    await VR开播.finish(seg)


@PSP开播.handle()
async def _(event: MessageEvent):
    seg = await _handle_live_list(
        api_url=cfg.psp_gift_api_base,  # https://psp.qianqiuzy.cn/gift
        title=cfg.psp_live_title,
        user_id=getattr(event, "user_id", 0),
    )
    await PSP开播.finish(seg)

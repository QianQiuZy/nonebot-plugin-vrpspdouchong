from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from nonebot import get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.params import CommandArg

from ..config import Config
from .douchong_daily import (
    build_brawl_daily_image,
    build_daily_image,
    normalize_day_arg,
)
from .douchong_table import (
    _duration_to_seconds,
    _seconds_to_duration,
    _to_float,
    _to_int,
    render_table_images,
)
from .query import _save_sc_image_file, _send_forward_images

cfg = get_plugin_config(Config)

# ==========================
# 1) Matcher：严格按你的要求
# ==========================
# VR斗虫：支持按日、按月和按年统计
VR斗虫 = on_command(
    "VR斗虫",
    aliases={"vr斗虫"},
    block=True,
    priority=5,
)

# PSP斗虫：仅接口和指令不同，其余完全相同
PSP斗虫 = on_command(
    "PSP斗虫",
    aliases={"psp斗虫"},
    block=True,
    priority=5,
)

大乱斗斗虫 = on_command(
    "大乱斗斗虫",
    block=True,
    priority=5,
)

_MONTH_RE_1 = re.compile(r"^(\d{4})(\d{2})$")
_MONTH_RE_2 = re.compile(r"^(\d{4})-(\d{2})$")
_YEAR_RE = re.compile(r"^(\d{4})$")


# ==========================
# 2) 通用：参数解析/格式化
# ==========================
def current_month_code() -> str:
    return time.strftime("%Y%m", time.localtime())


def normalize_month_arg(raw: str) -> Optional[str]:
    """
    规范化月份参数：
    - 接受 'YYYYMM' 或 'YYYY-MM'
    - 返回 'YYYYMM'；非法返回 None
    """
    if not raw:
        return None
    text = raw.strip()
    m1 = _MONTH_RE_1.fullmatch(text)
    m2 = _MONTH_RE_2.fullmatch(text)
    if m1:
        yyyy, mm = m1.group(1), m1.group(2)
    elif m2:
        yyyy, mm = m2.group(1), m2.group(2)
    else:
        return None
    try:
        mm_i = int(mm)
        if 1 <= mm_i <= 12:
            return f"{yyyy}{mm}"
    except Exception:
        return None
    return None


def build_year_month_codes(year: int, now_dt: Optional[datetime] = None) -> Optional[List[str]]:
    """
    年流水取数规则：
    - 目标年 < 当前年：拉取 1~12 月
    - 目标年 == 当前年：拉取 1~当前月
    - 目标年 > 当前年：非法
    """
    current = now_dt or datetime.now()
    current_year = current.year
    current_month = current.month

    if year > current_year:
        return None

    end_month = current_month if year == current_year else 12
    return [f"{year}{m:02d}" for m in range(1, end_month + 1)]


def normalize_period_arg(raw: str) -> Optional[Tuple[List[str], str, bool]]:
    """
    规范化统计周期参数：
    - 为空：当前月
    - YYYYMM 或 YYYY-MM：单月
    - YYYY：年累计（当年按 1~当前月，历史年按 1~12 月）
    返回: (month_codes, display_text, show_monthly_details)
    """
    text = (raw or "").strip()
    if not text:
        month_code = current_month_code()
        return [month_code], f"{month_code[:4]}-{month_code[4:]}", True

    month_code = normalize_month_arg(text)
    if month_code:
        return [month_code], f"{month_code[:4]}-{month_code[4:]}", True

    y = _YEAR_RE.fullmatch(text)
    if not y:
        return None

    year = int(y.group(1))
    month_codes = build_year_month_codes(year)
    if not month_codes:
        return None

    end_month = int(month_codes[-1][4:])
    return month_codes, f"{year}年 1-{end_month}月累计", False


def calc_live_duration_with_live_time(live_duration: Any, live_time: Any, now_ts: Optional[int] = None) -> str:
    """
    直播时长计算：now - live_time + live_duration
    - live_duration: "HH:MM:SS"
    - live_time: "YYYY-MM-DD HH:MM:SS"
    失败时回退原始 live_duration 字符串
    """
    try:
        duration_parts = str(live_duration).split(":")
        if len(duration_parts) != 3:
            return str(live_duration)

        h, m, s = map(int, duration_parts)
        base_seconds = h * 3600 + m * 60 + s

        live_dt = datetime.strptime(str(live_time), "%Y-%m-%d %H:%M:%S")
        live_ts = int(live_dt.timestamp())
        now_seconds = int(now_ts if now_ts is not None else time.time())

        total_seconds = max(0, now_seconds - live_ts + base_seconds)
        hh = total_seconds // 3600
        mm = (total_seconds % 3600) // 60
        ss = total_seconds % 60
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    except Exception:
        return str(live_duration)


def apply_live_duration_calc(data_list: List[Dict[str, Any]], now_ts: Optional[int] = None) -> None:
    """批量按 now-live_time+live_duration 更新 live_duration。"""
    current_ts = int(now_ts if now_ts is not None else time.time())
    for d in data_list:
        if not isinstance(d, dict):
            continue
        d["live_duration"] = calc_live_duration_with_live_time(
            d.get("live_duration", "00:00:00"),
            d.get("live_time", ""),
            current_ts,
        )


def build_query_source_text(event: MessageEvent) -> str:
    group_id = getattr(event, "group_id", None)
    user_id = getattr(event, "user_id", None)
    group_text = str(group_id) if group_id is not None else "未知群"
    user_text = str(user_id) if user_id is not None else "未知用户"
    return f"由群{group_text}中{user_text}查询"


# ==========================
# 3) 通用：HTTP 拉取
# ==========================
async def fetch_month_data(api_base: str, month_code: str) -> List[Dict[str, Any]]:
    url = f"{api_base}/by_month?month={month_code}"
    async with httpx.AsyncClient(timeout=cfg.vr_http_timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, list):
        raise ValueError("接口返回异常：非列表结构")
    return [d for d in data if isinstance(d, dict)]


def merge_monthly_data(all_rows: List[Dict[str, Any]], *, include_live_status: bool = False) -> List[Dict[str, Any]]:
    """按 room_id（缺失时退化到 anchor_name）聚合多月数据。"""
    numeric_sum_fields = [
        "effective_days", "guard_1", "guard_2", "guard_3", "fans_count", "payer_count",
        "blind_box_count", "blind_box_profit", "gift", "super_chat", "guard",
    ]
    int_sum_fields = ["effective_days", "guard_1", "guard_2", "guard_3", "fans_count", "payer_count", "blind_box_count"]
    max_fields = ["attention"]

    merged: Dict[str, Dict[str, Any]] = {}
    for row in all_rows:
        if not isinstance(row, dict):
            continue

        key = str(row.get("room_id") or row.get("anchor_name") or "")
        if not key:
            continue

        if key not in merged:
            base = dict(row)
            for f in numeric_sum_fields:
                base[f] = 0
            for f in max_fields:
                base[f] = 0
            base["status"] = 0
            base["live_duration_seconds"] = 0
            base["live_duration"] = "00:00:00"
            base["live_time"] = "0000-00-00 00:00:00"
            merged[key] = base

        target = merged[key]

        for f in numeric_sum_fields:
            target[f] = _to_float(target.get(f, 0)) + _to_float(row.get(f, 0))

        for f in int_sum_fields:
            target[f] = _to_int(round(_to_float(target.get(f, 0))))

        for f in max_fields:
            target[f] = max(_to_int(target.get(f, 0)), _to_int(row.get(f, 0)))

        target["live_duration_seconds"] = _to_int(target.get("live_duration_seconds", 0)) + _duration_to_seconds(
            row.get("live_duration", "00:00:00")
        )
        target["live_duration"] = _seconds_to_duration(target["live_duration_seconds"])

        if include_live_status and _to_int(row.get("status", 0)) == 1:
            target["status"] = 1
            target["live_time"] = str(row.get("live_time") or target.get("live_time") or "0000-00-00 00:00:00")

    for v in merged.values():
        v.pop("live_duration_seconds", None)

    return list(merged.values())


def _is_current_year_period(month_codes: List[str]) -> bool:
    if not month_codes:
        return False
    current_year = datetime.now().year
    return all(_to_int(code[:4], 0) == current_year for code in month_codes)


async def fetch_period_data(api_base: str, month_codes: List[str]) -> List[Dict[str, Any]]:
    """单月直出；多月聚合。"""
    if len(month_codes) == 1:
        return await fetch_month_data(api_base, month_codes[0])

    all_rows: List[Dict[str, Any]] = []
    for month_code in month_codes:
        month_rows = await fetch_month_data(api_base, month_code)
        all_rows.extend(month_rows)

    include_live_status = _is_current_year_period(month_codes)
    return merge_monthly_data(all_rows, include_live_status=include_live_status)


# ==========================
# 5) 通用 Handler（VR/PSP 复用）
# ==========================
async def send_douchong_images(
    bot: Bot,
    event: MessageEvent,
    *,
    title: str,
    period_display: str,
    images: list[str],
) -> None:
    image_paths = [
        _save_sc_image_file(
            image,
            anchor_name=title,
            page_no=index,
            total_pages=len(images),
        )
        for index, image in enumerate(images, start=1)
    ]
    await _send_forward_images(
        bot,
        event,
        title=title,
        image_paths=image_paths,
        anchor_name=period_display,
        item_label="张",
    )


async def _handle_douchong(
    bot: Bot,
    event: MessageEvent,
    arg: Message,
    *,
    api_base: str,
    title: str,
) -> MessageSegment | None:
    raw = ""
    try:
        raw = arg.extract_plain_text().strip()
    except Exception:
        raw = str(arg).strip()

    day_code = normalize_day_arg(raw)
    if day_code:
        try:
            b64 = await build_daily_image(
                api_base=api_base,
                day_code=day_code,
                title=title,
                query_source_text=build_query_source_text(event),
                timeout=cfg.vr_http_timeout,
            )
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as e:
            return MessageSegment.text(f"请求数据失败：{e}")
        if b64 is None:
            return MessageSegment.text(f"无数据：{day_code[:4]}-{day_code[4:6]}-{day_code[6:]}")
        return MessageSegment.image(f"base64://{b64}")

    period = normalize_period_arg(raw)
    if not period:
        return MessageSegment.text(
            "参数格式不正确，请使用 YYYY、YYYYMM、YYYY-MM 或 YYYYMMDD，例如：2026、202509、2025-09 或 20250913"
        )
    month_codes, period_display, show_monthly_details = period
    query_source_text = build_query_source_text(event)

    logger.info(
        f"[{title}] period={','.join(month_codes)} user={getattr(event, 'user_id', None)}"
    )

    try:
        data_list = await fetch_period_data(api_base, month_codes)
    except Exception as e:
        return MessageSegment.text(f"请求数据失败：{e}")

    if not data_list:
        return MessageSegment.text(f"无数据：{period_display}")

    # 单月保持动态时长；当年累计额外保留直播状态并动态增量时长
    if len(month_codes) == 1 or _is_current_year_period(month_codes):
        apply_live_duration_calc(data_list)

    try:
        images = render_table_images(
            title,
            data_list,
            period_display,
            query_source_text,
            show_monthly_details=show_monthly_details,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as e:
        logger.exception("render_table_images failed")
        return MessageSegment.text(f"生成图片失败：{e}")

    await send_douchong_images(
        bot,
        event,
        title=title,
        period_display=period_display,
        images=images,
    )
    return None

async def _handle_douchong_brawl(
    bot: Bot,
    event: MessageEvent,
    arg: Message,
) -> MessageSegment | None:
    """
    /大乱斗斗虫 [YYYYMMDD|YYYYMM|YYYY-MM]
    拉取 VR + PSP 两份数据，合并后按 total 排序，绘图复用 render_table_images。
    """
    raw = ""
    try:
        raw = arg.extract_plain_text().strip()
    except Exception:
        raw = str(arg).strip()

    day_code = normalize_day_arg(raw)
    if day_code:
        try:
            b64 = await build_brawl_daily_image(
                vr_api_base=cfg.vr_gift_api_base,
                psp_api_base=cfg.psp_gift_api_base,
                day_code=day_code,
                title="VRPSP大乱斗",
                query_source_text=build_query_source_text(event),
                timeout=cfg.vr_http_timeout,
            )
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as e:
            return MessageSegment.text(f"请求数据失败：{e}")
        if b64 is None:
            return MessageSegment.text(f"无数据：{day_code[:4]}-{day_code[4:6]}-{day_code[6:]}")
        return MessageSegment.image(f"base64://{b64}")

    period = normalize_period_arg(raw)
    if not period:
        return MessageSegment.text(
            "参数格式不正确，请使用 YYYY、YYYYMM、YYYY-MM 或 YYYYMMDD，例如：2026、202601、2026-01 或 20260913"
        )
    month_codes, period_display, show_monthly_details = period
    query_source_text = build_query_source_text(event)

    title = "VRPSP大乱斗"
    logger.info(f"[{title}] period={','.join(month_codes)} user={getattr(event, 'user_id', None)}")

    try:
        vr_list = await fetch_period_data(cfg.vr_gift_api_base, month_codes)
    except Exception as e:
        return MessageSegment.text(f"请求 VR 数据失败：{e}")

    try:
        psp_list = await fetch_period_data(cfg.psp_gift_api_base, month_codes)
    except Exception as e:
        return MessageSegment.text(f"请求 PSP 数据失败：{e}")

    # 平台标识：不改绘图结构，通过主播名加前缀区分来源
    for d in vr_list:
        if isinstance(d, dict):
            d["anchor_name"] = f"{d.get('anchor_name', '')}"
    for d in psp_list:
        if isinstance(d, dict):
            d["anchor_name"] = f"{d.get('anchor_name', '')}"

    data_list = [d for d in (vr_list + psp_list) if isinstance(d, dict)]
    if not data_list:
        return MessageSegment.text(f"无数据：{period_display}")

    # 单月保持动态时长；当年累计额外保留直播状态并动态增量时长
    if len(month_codes) == 1 or _is_current_year_period(month_codes):
        apply_live_duration_calc(data_list)

    try:
        images = render_table_images(
            title,
            data_list,
            period_display,
            query_source_text,
            show_monthly_details=show_monthly_details,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as e:
        logger.exception("render_table_images failed")
        return MessageSegment.text(f"生成图片失败：{e}")

    await send_douchong_images(
        bot,
        event,
        title=title,
        period_display=period_display,
        images=images,
    )
    return None

@VR斗虫.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    seg = await _handle_douchong(
        bot,
        event,
        arg,
        api_base=cfg.vr_gift_api_base,
        title=cfg.vr_douchong_title,
    )
    if seg is None:
        await VR斗虫.finish()
    await VR斗虫.finish(seg)


@PSP斗虫.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    seg = await _handle_douchong(
        bot,
        event,
        arg,
        api_base=cfg.psp_gift_api_base,
        title=cfg.psp_douchong_title,
    )
    if seg is None:
        await PSP斗虫.finish()
    await PSP斗虫.finish(seg)

@大乱斗斗虫.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    seg = await _handle_douchong_brawl(bot, event, arg)
    if seg is None:
        await 大乱斗斗虫.finish()
    await 大乱斗斗虫.finish(seg)

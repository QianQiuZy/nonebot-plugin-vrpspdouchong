from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from nonebot import get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.params import CommandArg

from ..api_client import create_client
from ..api_client import get as api_get
from ..config import Config
from ..message_sender import finish as finish_message, send as send_message
from .douchong_daily import (
    build_brawl_daily_image,
    build_daily_image,
    normalize_day_arg,
)
from .douchong_table import render_table_images
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

VUP斗虫 = on_command(
    "VUP斗虫",
    aliases={"vup斗虫", "Vup斗虫", "vUp斗虫", "vuP斗虫", "VUp斗虫", "VuP斗虫", "vUP斗虫"},
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
_YEAR_RE = re.compile(r"^[0-9]{4}$")
_CHINA_TIMEZONE = timezone(timedelta(hours=8))


# ==========================
# 2) 通用：参数解析/格式化
# ==========================
def current_month_code() -> str:
    return time.strftime("%Y%m", time.localtime())


def _beijing_now() -> datetime:
    return datetime.now(_CHINA_TIMEZONE)


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


@dataclass(frozen=True)
class QueryPeriod:
    code: str
    display: str
    annual: bool = False

    @property
    def show_monthly_details(self) -> bool:
        return not self.annual

    @property
    def show_live_status(self) -> bool:
        return not self.annual and self.code == current_month_code()


def normalize_period_arg(raw: str) -> Optional[QueryPeriod]:
    """空参数和 YYYYMM / YYYY-MM 查询月份，YYYY 直接查询整年。"""
    text = (raw or "").strip()
    month = normalize_month_arg(text) if text else current_month_code()
    if month:
        return QueryPeriod(month, f"{month[:4]}-{month[4:]}")

    now = _beijing_now()
    if not _YEAR_RE.fullmatch(text) or not 1 <= int(text) <= now.year:
        return None

    end_month = now.month if int(text) == now.year else 12
    return QueryPeriod(text, f"{int(text)}年 1-{end_month}月累计", annual=True)


def calc_live_duration_with_live_time(
    live_duration: Any,
    live_time: Any,
    now_ts: Optional[int] = None,
    *,
    annual_start: Optional[datetime] = None,
) -> str:
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
        now_seconds = int(now_ts if now_ts is not None else time.time())
        if annual_start is None:
            total_seconds = max(0, now_seconds - int(live_dt.timestamp()) + base_seconds)
        else:
            live_dt = live_dt.replace(tzinfo=_CHINA_TIMEZONE)
            active_start = max(live_dt, annual_start)
            total_seconds = base_seconds + max(0, now_seconds - int(active_start.timestamp()))
        hh = total_seconds // 3600
        mm = (total_seconds % 3600) // 60
        ss = total_seconds % 60
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    except Exception:
        return str(live_duration)


def apply_live_duration_calc(
    data_list: List[Dict[str, Any]], now_ts: Optional[int] = None, *, annual_start: Optional[datetime] = None,
) -> None:
    """批量按 now-live_time+live_duration 更新 live_duration。"""
    current_ts = int(now_ts if now_ts is not None else time.time())
    for d in data_list:
        if not isinstance(d, dict) or (annual_start is not None and d.get("status") not in (1, "1")):
            continue
        d["live_duration"] = calc_live_duration_with_live_time(
            d.get("live_duration", "00:00:00"),
            d.get("live_time", ""),
            current_ts,
            annual_start=annual_start,
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
async def fetch_period_data(api_base: str, period: QueryPeriod) -> List[Dict[str, Any]]:
    """使用服务端的月份或年度汇总，不在插件内按月拼接年度数据。"""
    params = {"year" if period.annual else "month": period.code}
    async with create_client(timeout=cfg.vr_http_timeout) as client:
        resp = await api_get(client, f"{api_base.rstrip('/')}/by_month", params=params)
        data = resp.json()

    if not isinstance(data, list):
        raise ValueError("接口返回异常：非列表结构")
    return [d for d in data if isinstance(d, dict)]


def update_period_live_duration(data_list: List[Dict[str, Any]], period: QueryPeriod) -> None:
    if not period.annual:
        apply_live_duration_calc(data_list)
        return
    now = _beijing_now()
    if int(period.code) == now.year:
        # 年度接口未提供在播计时游标，只能估算当年尚在进行的部分。
        annual_start = datetime(now.year, 1, 1, tzinfo=_CHINA_TIMEZONE)
        apply_live_duration_calc(data_list, int(now.timestamp()), annual_start=annual_start)


# ==========================
# 5) 通用 Handler（VR/PSP/VUP 复用）
# ==========================
async def send_douchong_images(
    bot: Bot,
    event: MessageEvent,
    *,
    title: str,
    period_display: str,
    images: list[str],
) -> None:
    if len(images) == 1:
        await send_message(bot, event, MessageSegment.image(f"base64://{images[0]}"))
        return

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
    period_display = period.display
    query_source_text = build_query_source_text(event)

    logger.info(
        f"[{title}] period={period.code} user={getattr(event, 'user_id', None)}"
    )

    try:
        data_list = await fetch_period_data(api_base, period)
    except Exception as e:
        return MessageSegment.text(f"请求数据失败：{e}")

    if not data_list:
        return MessageSegment.text(f"无数据：{period_display}")

    update_period_live_duration(data_list, period)

    try:
        images = render_table_images(
            title,
            data_list,
            period_display,
            query_source_text,
            show_monthly_details=period.show_monthly_details,
            show_live_status=period.show_live_status,
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
    /大乱斗斗虫 [YYYYMMDD|YYYYMM|YYYY-MM|YYYY]
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
    period_display = period.display
    query_source_text = build_query_source_text(event)

    title = "VRPSP大乱斗"
    logger.info(f"[{title}] period={period.code} user={getattr(event, 'user_id', None)}")

    try:
        vr_list = await fetch_period_data(cfg.vr_gift_api_base, period)
    except Exception as e:
        return MessageSegment.text(f"请求 VR 数据失败：{e}")

    try:
        psp_list = await fetch_period_data(cfg.psp_gift_api_base, period)
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

    update_period_live_duration(data_list, period)

    try:
        images = render_table_images(
            title,
            data_list,
            period_display,
            query_source_text,
            show_monthly_details=period.show_monthly_details,
            show_live_status=period.show_live_status,
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
    await finish_message(VR斗虫, seg)


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
    await finish_message(PSP斗虫, seg)

@VUP斗虫.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    seg = await _handle_douchong(
        bot,
        event,
        arg,
        api_base=cfg.vup_gift_api_base,
        title=cfg.vup_douchong_title,
    )
    if seg is None:
        await VUP斗虫.finish()
    await finish_message(VUP斗虫, seg)


@大乱斗斗虫.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    seg = await _handle_douchong_brawl(bot, event, arg)
    if seg is None:
        await 大乱斗斗虫.finish()
    await finish_message(大乱斗斗虫, seg)

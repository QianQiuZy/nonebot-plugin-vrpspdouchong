from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from nonebot import get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.params import CommandArg

from ..config import Config
from ..toolkit import PicGenerator, Color, timestamp_format

cfg = get_plugin_config(Config)

# ==========================
# 1) Matcher：严格按你的要求
# ==========================
# VR斗虫：仅支持 /VR斗虫 与 /vr斗虫
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


def format_duration(hms: str) -> str:
    """将 'HH:MM:SS' 转为 'xx.x小时'；异常或格式不符时回退原字符串"""
    try:
        parts = str(hms).split(":")
        if len(parts) == 3:
            h, m, s = map(int, parts)
            total_hours = h + m / 60 + s / 3600
            return f"{total_hours:.1f}小时"
    except Exception:
        pass
    return str(hms)


def format_fans(attention: int) -> str:
    try:
        if attention >= 10000:
            return f"{attention / 10000:.1f}万"
        return str(attention)
    except Exception:
        return str(attention)


def format_count(v: Optional[int]) -> str:
    """
    守护数量 / 粉丝团数量的统一格式：
    - 当前月有数据 -> 直接转 int 显示
    - 历史月为 None -> 显示 "-"
    """
    if v is None:
        return "-"
    try:
        return str(int(v))
    except Exception:
        return "-"


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


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


# ==========================
# 4) 通用：绘图（完全一致）
# ==========================
def render_table_image(title: str, data_list: List[Dict[str, Any]], month_code: str) -> str:
    # ---------- 预处理：计算总计、格式化、排序 ----------
    for d in data_list:
        gift = _to_float(d.get("gift", 0))
        sc = _to_float(d.get("super_chat", 0))
        guard = _to_float(d.get("guard", 0))
        d["total"] = gift + sc + guard

        d["duration_fmt"] = format_duration(d.get("live_duration", "00:00:00"))
        d["fans_fmt"] = format_fans(_to_int(d.get("attention", 0)))

    data_list.sort(key=lambda x: _to_float(x.get("total", 0)), reverse=True)

    # ---------- 绘图参数 ----------
    row_height = 60
    col_widths = [
        300,  # 主播名称
        140,  # 粉丝数
        150,  # 直播状态
        200,  # 直播时间
        100,  # 有效天
        90,   # 舰长数量
        90,   # 提督数量
        90,   # 总督数量
        120,  # 粉丝团数量
        100,  # 盲盒数
        130,  # 盲盒盈亏
        150,  # 礼物
        150,  # SC
        150,  # 上舰金额
        200,  # 总计
    ]
    headers = [
        "主播名称", "粉丝数", "直播状态", "直播时间", "有效天",
        "舰长", "提督", "总督", "粉丝团","盲盒数", "盲盒盈亏",
        "礼物", "SC", "上舰", "总计",
    ]

    table_width = sum(col_widths) + 40
    table_height = row_height * (len(data_list) + 1) + 40
    canvas_width = table_width
    canvas_height = table_height + 160

    pic = PicGenerator(canvas_width, canvas_height)
    pic.set_pos(0, 0).draw_rounded_rectangle(0, 0, canvas_width, canvas_height, 35, Color.WHITE)

    # ---------- 标题与时间 ----------
    LEFT_PADDING = 20
    TIME_Y = 90
    MONTH_Y = 120
    TIP_X_OFFSET = 300

    pic.set_pos(LEFT_PADDING, 30).draw_text(title, [Color.BLACK])

    now_str = timestamp_format(int(time.time()), "%Y-%m-%d %H:%M:%S")
    pic.set_pos(LEFT_PADDING, TIME_Y).draw_text(now_str, [Color.GRAY])

    pic.set_pos(LEFT_PADDING + TIP_X_OFFSET, TIME_Y).draw_text("数据为每月1号开始统计，月底清零。", [Color.GRAY])

    month_disp = f"{month_code[:4]}-{month_code[4:]}"
    pic.set_pos(LEFT_PADDING, MONTH_Y).draw_text(f"统计月份：{month_disp}", [Color.GRAY])

    # ---------- 表格绘制 ----------
    origin_x = 20
    origin_y = 160
    cur_y = origin_y

    # 表头
    pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 12, Color.DEEPSKYBLUE)
    cur_x = origin_x + 10
    for w, h in zip(col_widths, headers):
        pic.set_pos(cur_x, cur_y + 18).draw_text(h, [Color.WHITE])
        cur_x += w

    cur_y += row_height

    # 表体
    for idx, d in enumerate(data_list):
        cur_x = origin_x + 10

        status_txt = "直播中" if _to_int(d.get("status", 0)) == 1 else "未开播"
        status_col = Color.DEEPSKYBLUE if _to_int(d.get("status", 0)) == 1 else Color.BLACK

        fields: List[Tuple[str, Any]] = [
            (str(d.get("anchor_name", "")), Color.BLACK),
            (str(d.get("fans_fmt", "0")), Color.BLACK),
            (status_txt, status_col),
            (str(d.get("duration_fmt", "")), Color.BLACK),
            (str(d.get("effective_days", "")), Color.BLACK),

            (format_count(d.get("guard_1")), Color.BLACK),
            (format_count(d.get("guard_2")), Color.BLACK),
            (format_count(d.get("guard_3")), Color.BLACK),
            (format_count(d.get("fans_count")), Color.BLACK),
            (format_count(d.get("blind_box_count")), Color.BLACK),

            (f"{_to_float(d.get('blind_box_profit', 0)):.1f}", Color.BLACK),
            (f"{_to_float(d.get('gift', 0)):.1f}", Color.BLACK),
            (f"{_to_float(d.get('super_chat', 0)):.1f}", Color.BLACK),
            (f"{_to_float(d.get('guard', 0)):.1f}", Color.BLACK),
            (f"{_to_float(d.get('total', 0)):.1f}", Color.BLACK),
        ]

        bg = Color.LIGHTGRAY if (idx % 2 == 0) else Color.WHITE
        pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, bg)

        for w, (text, txt_color) in zip(col_widths, fields):
            pic.set_pos(cur_x, cur_y + 18).draw_text(str(text), [txt_color])
            cur_x += w

        cur_y += row_height

    # ---------- 底部 ----------
    pic.set_pos(canvas_width - 220, canvas_height - 40)
    pic.draw_text_right(0, "Designed by QianQiuZy", Color.GRAY)
    pic.crop_and_paste_bottom()

    return pic.base64()


# ==========================
# 5) 通用 Handler（VR/PSP 复用）
# ==========================
async def _handle_douchong(event: MessageEvent, arg: Message, *, api_base: str, title: str):
    raw = ""
    try:
        raw = arg.extract_plain_text().strip()
    except Exception:
        raw = str(arg).strip()

    if raw:
        month_code = normalize_month_arg(raw)
        if not month_code:
            return MessageSegment.text(
                "月份格式不正确，请使用 YYYYMM 或 YYYY-MM，例如：202509 或 2025-09"
            )
    else:
        month_code = current_month_code()

    logger.info(f"[{title}] month={month_code} user={getattr(event, 'user_id', None)}")

    try:
        data_list = await fetch_month_data(api_base, month_code)
    except Exception as e:
        return MessageSegment.text(f"请求数据失败：{e}")

    if not data_list:
        return MessageSegment.text(f"无数据：{month_code}")

    try:
        b64 = render_table_image(title, data_list, month_code)
    except Exception as e:
        logger.exception("render_table_image failed")
        return MessageSegment.text(f"生成图片失败：{e}")

    return MessageSegment.image(f"base64://{b64}")

async def _handle_douchong_brawl(event: MessageEvent, arg: Message):
    """
    /大乱斗斗虫 [YYYYMM|YYYY-MM]
    拉取 VR + PSP 两份数据，合并后按 total 排序，绘图复用 render_table_image。
    """
    raw = ""
    try:
        raw = arg.extract_plain_text().strip()
    except Exception:
        raw = str(arg).strip()

    if raw:
        month_code = normalize_month_arg(raw)
        if not month_code:
            # 按你的需求强调 YYYYMM，同时兼容 YYYY-MM（normalize_month_arg 已支持）
            return MessageSegment.text("月份格式不正确，请使用 YYYYMM，例如：202601")
    else:
        month_code = current_month_code()

    title = "VRPSP大乱斗"
    logger.info(f"[{title}] month={month_code} user={getattr(event, 'user_id', None)}")

    try:
        vr_list = await fetch_month_data(cfg.vr_gift_api_base, month_code)
    except Exception as e:
        return MessageSegment.text(f"请求 VR 数据失败：{e}")

    try:
        psp_list = await fetch_month_data(cfg.psp_gift_api_base, month_code)
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
        return MessageSegment.text(f"无数据：{month_code}")

    try:
        b64 = render_table_image(title, data_list, month_code)
    except Exception as e:
        logger.exception("render_table_image failed")
        return MessageSegment.text(f"生成图片失败：{e}")

    return MessageSegment.image(f"base64://{b64}")

@VR斗虫.handle()
async def _(event: MessageEvent, arg: Message = CommandArg()):
    seg = await _handle_douchong(
        event,
        arg,
        api_base=cfg.vr_gift_api_base,
        title=cfg.vr_douchong_title,
    )
    await VR斗虫.finish(seg)


@PSP斗虫.handle()
async def _(event: MessageEvent, arg: Message = CommandArg()):
    seg = await _handle_douchong(
        event,
        arg,
        api_base=cfg.psp_gift_api_base,
        title=cfg.psp_douchong_title,
    )
    await PSP斗虫.finish(seg)

@大乱斗斗虫.handle()
async def _(event: MessageEvent, arg: Message = CommandArg()):
    seg = await _handle_douchong_brawl(event, arg)
    await 大乱斗斗虫.finish(seg)
# src/plugins/douchong/commands/query.py
from __future__ import annotations

import re
import time
import datetime
from typing import Any, Dict, List, Optional, Tuple
import asyncio
import httpx
from nonebot import get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageSegment,
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.params import CommandArg
from nonebot.log import logger

from ..config import Config
from ..toolkit import PicGenerator, Color, timestamp_format

cfg = get_plugin_config(Config)

# -------------------- commands --------------------
查直播 = on_command("查直播", block=True, priority=5)
查SC = on_command("查SC", block=True, priority=5)
查流水 = on_command("查流水", priority=20, block=True)

# -------------------- utils: month --------------------
def current_month_code() -> str:
    return time.strftime("%Y%m", time.localtime())


def normalize_month_arg(raw: str) -> Optional[str]:
    if not raw:
        return None
    text = raw.strip()
    m1 = re.fullmatch(r"(\d{4})(\d{2})", text)
    m2 = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if m1:
        yyyy, mm = m1.group(1), m1.group(2)
    elif m2:
        yyyy, mm = m2.group(1), m2.group(2)
    else:
        return None
    try:
        if 1 <= int(mm) <= 12:
            return f"{yyyy}{mm}"
    except Exception:
        pass
    return None


# -------------------- utils: parse args --------------------
def _parse_anchor_and_month(arg_str: str) -> Tuple[str, str]:
    """
    输入：'主播名 [YYYYMM|YYYY-MM]'
    输出：(anchor_kw, month_code)
    """
    raw = (arg_str or "").strip()
    if not raw:
        return "", current_month_code()

    parts = re.split(r"\s+", raw)
    maybe_month = normalize_month_arg(parts[-1]) if parts else None
    if maybe_month:
        month_code = maybe_month
        anchor_kw = " ".join(parts[:-1]).strip()
    else:
        month_code = current_month_code()
        anchor_kw = raw
    return anchor_kw, month_code


# -------------------- utils: anchor search --------------------
def _match_anchor(items: List[Dict[str, Any]], keyword: str) -> Optional[Dict[str, Any]]:
    return next((it for it in items if keyword in str(it.get("anchor_name", ""))), None)


async def _fetch_json(url: str) -> Any:
    async with httpx.AsyncClient(timeout=cfg.vr_http_timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _fetch_gift_list(base: str) -> List[Dict[str, Any]]:
    """
    base 是 gift 根：例如 https://vr.qianqiuzy.cn/gift
    """
    data = await _fetch_json(base)
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [d for d in data["data"] if isinstance(d, dict)]
    return []


async def _locate_room_by_anchor(anchor_kw: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    通过 /gift 列表搜索主播，返回 (chosen_base, match_item)
    顺序请求（稳定优先）。
    """
    bases = [cfg.vr_gift_api_base, cfg.psp_gift_api_base]

    for base in bases:
        try:
            data = await _fetch_json(base)
            lst = data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else None)
            if not isinstance(lst, list):
                continue

            match = _match_anchor([x for x in lst if isinstance(x, dict)], anchor_kw)
            if match:
                return base, match

        except Exception as e:
            logger.warning(f"_locate_room_by_anchor fetch {base} failed: {e}")
            continue

    return None, None

# -------------------- utils: time --------------------
def _parse_dt(s: str) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _sec_to_hms(total_seconds: int) -> str:
    if total_seconds < 0:
        total_seconds = 0
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ========================= ① 查直播：查询函数 =========================
async def query_live_sessions(*, base: str, room_id: str, month_code: str) -> List[Dict[str, Any]]:
    url = f"{base}/live_sessions?room_id={room_id}&month={month_code}"
    payload = await _fetch_json(url)

    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        return []
    return [x for x in payload["sessions"] if isinstance(x, dict)]


# ========================= ② 查直播：渲染函数 =========================
def render_live_sessions_image(
    *,
    anchor_name: str,
    room_id: str,
    month_code: str,
    sessions: List[Dict[str, Any]],
) -> str:
    now = datetime.datetime.now()

    rows: List[Dict[str, Any]] = []
    total_danmu = 0
    total_box = 0
    total_profit = 0.0
    total_gift = 0.0
    total_guard = 0.0
    total_sc = 0.0
    total_sum = 0.0
    total_seconds = 0

    for s in sessions:
        start_str = str(s.get("start_time") or "")
        end_str = str(s.get("end_time") or "")
        title = str(s.get("title") or "")

        try:
            danmu = int(s.get("danmaku_count") or 0)
        except Exception:
            danmu = 0

        # NEW: 平均同接/最高同接
        try:
            avg_cc = int(round(float(s.get("avg_concurrency") or 0)))
        except Exception:
            avg_cc = 0
        try:
            max_cc = int(s.get("max_concurrency") or 0)
        except Exception:
            max_cc = 0

        blind_box_count = int(s.get("blind_box_count") or 0)
        blind_box_profit = float(s.get("blind_box_profit") or 0)
        gift = float(s.get("gift") or 0)
        guard = float(s.get("guard") or 0)
        sc = float(s.get("super_chat") or 0)
        subtotal = gift + guard + sc

        dt_start = _parse_dt(start_str) if start_str else None
        dt_end = _parse_dt(end_str) if end_str else None

        if dt_start:
            if dt_end:
                dur_sec = int((dt_end - dt_start).total_seconds())
                end_disp = end_str
            else:
                dur_sec = int((now - dt_start).total_seconds())
                end_disp = "直播中"
        else:
            dur_sec = 0
            end_disp = end_str or "—"

        rows.append(
            {
                "start": start_str or "—",
                "end": end_disp,
                "duration": _sec_to_hms(dur_sec),
                "danmu": danmu,
                "avg_cc": avg_cc,   # NEW
                "max_cc": max_cc,   # NEW
                "title": title,
                "blind_box_count": blind_box_count,
                "blind_box_profit": blind_box_profit,
                "gift": gift,
                "guard": guard,
                "sc": sc,
                "sum": subtotal,
            }
        )

        total_box += blind_box_count
        total_profit += blind_box_profit
        total_danmu += danmu
        total_gift += gift
        total_guard += guard
        total_sc += sc
        total_sum += subtotal
        total_seconds += max(0, dur_sec)

    # NEW: 在“弹幕数”和“本场直播标题”之间插入两列，宽度均 150
    col_widths = [350, 350, 200, 120, 150, 150, 600, 100, 120, 150, 150, 150, 200]
    headers = ["开播时间", "下播时间", "本场直播时间", "弹幕数", "平均同接", "最高同接", "本场直播标题", "盲盒数", "盲盒盈亏", "礼物", "舰长", "SC", "总计"]

    row_height = 60
    table_width = sum(col_widths) + 40
    header_h = 160
    n_rows = max(1, len(rows))
    table_height = row_height * (n_rows + 2) + 40  # 表头+合计
    canvas_width = table_width
    canvas_height = header_h + table_height

    pic = PicGenerator(canvas_width, canvas_height)
    pic.set_pos(0, 0).draw_rounded_rectangle(0, 0, canvas_width, canvas_height, 35, Color.WHITE)

    LEFT = 20
    TITLE_Y = 30
    ROOM_Y = 90
    TIME_Y = 120

    month_label = "本月" if month_code == current_month_code() else f"{month_code}月"
    pic.set_pos(LEFT, TITLE_Y).draw_text(f"{anchor_name}{month_label}直播情况", [Color.BLACK])
    pic.set_pos(LEFT, ROOM_Y).draw_text(f"房间号：{room_id}", [Color.GRAY])
    pic.set_pos(LEFT, TIME_Y).draw_text(
        f"查询时间：{timestamp_format(int(time.time()), '%Y-%m-%d %H:%M:%S')}",
        [Color.GRAY],
    )

    origin_x = 20
    origin_y = header_h
    cur_y = origin_y

    # 表头
    pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 12, Color.DEEPSKYBLUE)
    cur_x = origin_x + 10
    for w, h in zip(col_widths, headers):
        pic.set_pos(cur_x, cur_y + 18).draw_text(h, [Color.WHITE])
        cur_x += w

    # 表体
    cur_y += row_height
    if rows:
        for idx, r in enumerate(rows):
            bg = Color.LIGHTGRAY if (idx % 2 == 0) else Color.WHITE
            pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, bg)

            # NEW: 插入 avg_cc / max_cc 两列
            cells = [
                r["start"],
                r["end"],
                r["duration"],
                str(r["danmu"]),
                str(r["avg_cc"]),   # NEW
                str(r["max_cc"]),   # NEW
                r["title"],
                str(r["blind_box_count"]),
                f"{r['blind_box_profit']:.1f}",
                f"{r['gift']:.1f}",
                f"{r['guard']:.1f}",
                f"{r['sc']:.1f}",
                f"{r['sum']:.1f}",
            ]
            cur_x = origin_x + 10
            for w, txt in zip(col_widths, cells):
                pic.set_pos(cur_x, cur_y + 18).draw_text(str(txt), [Color.BLACK])
                cur_x += w
            cur_y += row_height
    else:
        pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, Color.WHITE)
        pic.set_pos(origin_x + 10, cur_y + 18).draw_text("（无记录）", [Color.BLACK])
        cur_y += row_height

    # 合计行
    pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_height, 0, Color.LIGHTGRAY)

    # NEW: 合计行补齐两列占位（平均同接/最高同接），避免列数不匹配
    total_cells = [
        f"场次：{len(rows)}",
        "",
        _sec_to_hms(total_seconds),
        str(total_danmu),
        "",  # avg_cc 合计不计算
        "",  # max_cc 合计不计算
        "",  # title
        str(total_box),
        f"{total_profit:.1f}",
        f"{total_gift:.1f}",
        f"{total_guard:.1f}",
        f"{total_sc:.1f}",
        f"{total_sum:.1f}",
    ]
    cur_x = origin_x + 10
    for w, txt in zip(col_widths, total_cells):
        pic.set_pos(cur_x, cur_y + 18).draw_text(str(txt), [Color.BLACK])
        cur_x += w

    # 版权
    pic.set_pos(canvas_width - 220, canvas_height - 40)
    pic.draw_text_right(0, "Designed by QianQiuZy", Color.GRAY)

    pic.crop_and_paste_bottom()
    return pic.base64()

# ========================= ③ 查SC：查询函数 =========================
async def query_sc_list(*, base: str, room_id: str, month_code: str) -> List[Dict[str, Any]]:
    url = f"{base}/sc?room_id={room_id}&month={month_code}"
    payload = await _fetch_json(url)

    if isinstance(payload, dict):
        lst = payload.get("list")
        if isinstance(lst, list):
            return [x for x in lst if isinstance(x, dict)]
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


# ========================= ④ 查SC：渲染函数（分页多图） =========================
SC_MAX_PAGE_HEIGHT = 16000
BASE_ROW_H = 60
EXTRA_PER_LINE = 28
MSG_MAX_CHARS_PER_LINE = 20

def clean_sc_message(raw: str) -> str:
    if not raw:
        return ""
    s = str(raw).replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def wrap_sc_message(text: str, max_chars: int) -> List[str]:
    if not text:
        return [""]
    lines: List[str] = []
    i = 0
    while i < len(text):
        lines.append(text[i : i + max_chars])
        i += max_chars
    return lines or [""]

def limit_uname_visual(uname: str, max_units: float = 12.0) -> str:
    uname = uname or ""
    units = 0.0
    kept: List[str] = []
    for ch in uname:
        w = 0.5 if ord(ch) < 128 else 1.0
        if units + w > max_units:
            break
        kept.append(ch)
        units += w
    if len(kept) == len(uname):
        return uname
    ellipsis_w = 1.0
    while kept and units + ellipsis_w > max_units:
        last = kept.pop()
        units -= (0.5 if ord(last) < 128 else 1.0)
    kept.append("…")
    return "".join(kept)

def _safe_dt(s: str) -> datetime.datetime:
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.datetime.min

def _paginate_rows_by_height(
    rows: List[Dict[str, Any]],
    *,
    max_canvas_h: int,
    header_h: int,
    table_header_h: int,
    table_padding_h: int = 40,
) -> List[Tuple[int, List[Dict[str, Any]]]]:
    max_data_h = max_canvas_h - header_h - table_header_h - table_padding_h
    if max_data_h <= 0:
        max_data_h = 1

    pages: List[Tuple[int, List[Dict[str, Any]]]] = []
    cur: List[Dict[str, Any]] = []
    cur_h = 0
    start_idx = 0
    global_idx = 0

    for r in rows:
        rh = int(r.get("row_height") or 0)
        if cur and (cur_h + rh > max_data_h):
            pages.append((start_idx, cur))
            cur = []
            cur_h = 0
            start_idx = global_idx

        cur.append(r)
        cur_h += rh
        global_idx += 1

    if cur:
        pages.append((start_idx, cur))

    return pages or [(0, [])]

def render_sc_images(
    *,
    anchor_name: str,
    room_id: str,
    month_code: str,
    sc_list: List[Dict[str, Any]],
) -> List[str]:
    # 列设置
    col_widths = [350, 350, 300, 100, 700]
    headers = ["发送时间", "发送人", "UID", "价格", "内容"]

    sc_sorted = sorted(sc_list, key=lambda it: _safe_dt(str(it.get("send_time", ""))))

    rows: List[Dict[str, Any]] = []
    for item in sc_sorted:
        send_time = str(item.get("send_time", "") or "")
        uname_raw = str(item.get("uname", "") or "")
        uname = limit_uname_visual(uname_raw, max_units=12.0)
        uid = str(item.get("uid", "") or "")[:16]

        try:
            price_val = float(item.get("price") or 0)
        except Exception:
            price_val = 0.0
        price_str = str(int(round(price_val)))[:5]

        msg_clean = clean_sc_message(str(item.get("message", "") or ""))
        msg_lines = wrap_sc_message(msg_clean, MSG_MAX_CHARS_PER_LINE)
        line_count = max(1, len(msg_lines))
        row_height = BASE_ROW_H + (line_count - 1) * EXTRA_PER_LINE

        rows.append(
            {
                "time": send_time,
                "uname": uname,
                "uid": uid,
                "price": price_str,
                "msg_lines": msg_lines,
                "row_height": row_height,
            }
        )

    header_h = 160
    table_header_h = BASE_ROW_H
    pages = _paginate_rows_by_height(
        rows,
        max_canvas_h=SC_MAX_PAGE_HEIGHT,
        header_h=header_h,
        table_header_h=table_header_h,
        table_padding_h=40,
    )

    out_b64: List[str] = []
    total_pages = len(pages)

    for page_no, (global_start_idx, page_rows) in enumerate(pages, start=1):
        data_height = sum(int(r["row_height"]) for r in page_rows) if page_rows else BASE_ROW_H
        table_width = sum(col_widths) + 40
        table_height = table_header_h + data_height + 40
        canvas_width = table_width
        canvas_height = header_h + table_height

        pic = PicGenerator(canvas_width, canvas_height)
        pic.set_pos(0, 0).draw_rounded_rectangle(0, 0, canvas_width, canvas_height, 35, Color.WHITE)

        LEFT = 20
        TITLE_Y = 30
        ROOM_Y = 90
        TIME_Y = 120

        month_disp = f"{month_code[:4]}-{month_code[4:]}" if len(month_code) == 6 else month_code
        title_text = f"{anchor_name} {month_disp} SC 记录（{page_no}/{total_pages}）"
        pic.set_pos(LEFT, TITLE_Y).draw_text(title_text, [Color.BLACK])
        pic.set_pos(LEFT, ROOM_Y).draw_text(f"房间号：{room_id}", [Color.GRAY])

        now_str = timestamp_format(int(time.time()), "%Y-%m-%d %H:%M:%S")
        count_str = f"共 {len(rows)} 条" if rows else "暂无记录"
        pic.set_pos(LEFT, TIME_Y).draw_text(f"查询时间：{now_str}  |  {count_str}", [Color.GRAY])

        origin_x = 20
        origin_y = header_h
        cur_y = origin_y

        # 表头
        pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, table_header_h, 12, Color.DEEPSKYBLUE)
        cur_x = origin_x + 10
        for w, h in zip(col_widths, headers):
            pic.set_pos(cur_x, cur_y + 18).draw_text(h, [Color.WHITE])
            cur_x += w

        cur_y += table_header_h

        if page_rows:
            for idx, r in enumerate(page_rows):
                row_h = int(r["row_height"])
                bg = Color.LIGHTGRAY if ((global_start_idx + idx) % 2 == 0) else Color.WHITE
                pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, row_h, 0, bg)

                cur_x = origin_x + 10
                base_y = cur_y + 18

                cells = [r["time"], r["uname"], r["uid"], r["price"]]
                for w, txt in zip(col_widths[:4], cells):
                    pic.set_pos(cur_x, base_y).draw_text(str(txt), [Color.BLACK])
                    cur_x += w

                msg_x = cur_x
                y = base_y
                for line in r["msg_lines"]:
                    pic.set_pos(msg_x, y).draw_text(line, [Color.BLACK])
                    y += EXTRA_PER_LINE

                cur_y += row_h
        else:
            pic.draw_rounded_rectangle(origin_x, cur_y, table_width - 40, BASE_ROW_H, 0, Color.WHITE)
            pic.set_pos(origin_x + 10, cur_y + 18).draw_text("（本月暂无 SC 记录）", [Color.BLACK])

        # 版权
        pic.set_pos(canvas_width - 220, canvas_height - 40)
        pic.draw_text_right(0, "Designed by QianQiuZy", Color.GRAY)

        pic.crop_and_paste_bottom()
        out_b64.append(pic.base64())

    return out_b64


# ========================= ⑤ 查SC：发送函数（合并转发） =========================
async def _send_forward_images(
    bot: Bot,
    event: MessageEvent,
    *,
    title: str,
    images_b64: List[str],
    anchor_name: str = "",
) -> None:
    """
    伪造合并转发消息：
    - 每页一条 node_custom，内容为图片
    - 使用 bot.self_id 作为发送者，昵称固定为 title（或你也可改为 cfg.xxx）
    """
    if not images_b64:
        return

    try:
        uin = int(bot.self_id)
    except Exception:
        uin = 0

    nodes = []
    # 可选：首节点放一条说明文本（稳定，且转发预览更友好）
    nodes.append(
        MessageSegment.node_custom(
            user_id=uin,
            nickname=title,
            content=Message(f"{anchor_name} {title}（共 {len(images_b64)} 页）"),
        )
    )
    for i, b64 in enumerate(images_b64, start=1):
        img_seg = MessageSegment.image(f"base64://{b64}")
        nodes.append(
            MessageSegment.node_custom(
                user_id=uin,
                nickname=title,
                content=Message([MessageSegment.text(f"第 {i}/{len(images_b64)} 页"), img_seg]),
            )
        )

    if isinstance(event, GroupMessageEvent):
        await bot.call_api("send_forward_msg", group_id=event.group_id, messages=nodes)
    elif isinstance(event, PrivateMessageEvent):
        await bot.call_api("send_private_forward_msg", user_id=event.user_id, messages=nodes)
    else:
        # 兜底：按普通消息发送（极少发生）
        await bot.send(event, MessageSegment.text("不支持的事件类型，无法发送合并消息"))


def _dedup_by_anchor_room(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 (anchor_name, room_id) 去重，保持稳定顺序。"""
    seen: set[Tuple[str, Any]] = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        key = (str(it.get("anchor_name") or ""), it.get("room_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


async def _fetch_month_list(client: httpx.AsyncClient, base: str, month_code: str) -> List[Dict[str, Any]]:
    url = f"{base}/by_month"
    try:
        r = await client.get(url, params={"month": month_code})
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return [x for x in data["data"] if isinstance(x, dict)]
        return []
    except Exception:
        return []


async def fetch_all_data_by_month(month_code: str) -> List[Dict[str, Any]]:
    """并行拉取 VR+PSP 按月数据并合并去重。"""
    bases = [cfg.vr_gift_api_base, cfg.psp_gift_api_base]
    async with httpx.AsyncClient(timeout=cfg.vr_http_timeout) as client:
        lists = await asyncio.gather(*[_fetch_month_list(client, b, month_code) for b in bases])
    merged: List[Dict[str, Any]] = []
    for lst in lists:
        merged.extend(lst or [])
    return _dedup_by_anchor_room(merged)


def _format_duration_hours(live_duration: str) -> str:
    """HH:MM:SS -> xx.xx 小时（失败则返回原串）"""
    try:
        parts = (live_duration or "").split(":")
        if len(parts) == 3:
            h, m, s = map(int, parts)
            total_hours = h + m / 60 + s / 3600
            return f"{total_hours:.2f}小时"
    except Exception:
        pass
    return live_duration or "00:00:00"


def render_liushui_card(
    *,
    month_code: str,
    anchor: str,
    room_id: Any,
    attention: Any,
    live_duration: str,
    effective_days: Any,
    gift_value: Any,
    guard_value: Any,
    sc_value: Any,
) -> str:
    gift = float(gift_value or 0)
    guard = float(guard_value or 0)
    sc = float(sc_value or 0)
    total = gift + guard + sc

    month_label = "本月" if month_code == current_month_code() else f"{month_code}月"
    month_disp = f"{month_code[:4]}-{month_code[4:]}" if len(month_code) == 6 else month_code

    duration_hours_str = _format_duration_hours(str(live_duration or "00:00:00"))

    W = 720
    H = 8000  # 预留足够高度，最后会 crop
    LEFT = 24

    pic = PicGenerator(W, H)
    pic.set_pos(0, 0).draw_rounded_rectangle(0, 0, W, H, 35, Color.WHITE)

    y = 24

    # 标题
    pic.set_pos(LEFT, y).draw_text(f"{anchor} · 流水概览", Color.BLACK)
    y += 52
    pic.set_pos(LEFT, y).draw_text(f"统计月份：{month_disp}（{month_label}）", Color.GRAY)
    y += 42
    pic.set_pos(LEFT, y).draw_text(f"房间号：{room_id}    粉丝数：{attention}", Color.GRAY)
    y += 42
    pic.set_pos(LEFT, y).draw_text(
        f"查询时间：{timestamp_format(int(time.time()), '%Y-%m-%d %H:%M:%S')}",
        Color.GRAY,
    )
    y += 30

    # 分隔
    pic.set_pos(LEFT, y).draw_text("—" * 60, Color.LIGHTGRAY)
    y += 34

    # 时长
    pic.set_pos(LEFT, y).draw_text([f"{month_label}时长：", duration_hours_str], [Color.DEEPSKYBLUE, Color.BLACK])
    y += 42
    pic.set_pos(LEFT, y).draw_text([f"有效天：", str(effective_days)], [Color.DEEPSKYBLUE, Color.BLACK])
    y += 30

    pic.set_pos(LEFT, y).draw_text("—" * 60, Color.LIGHTGRAY)
    y += 34

    # 流水
    pic.set_pos(LEFT, y).draw_text(f"{month_label}流水：", Color.DEEPSKYBLUE)
    y += 42
    pic.set_pos(LEFT, y).draw_text([f"礼物：", f"{gift:.1f}"], [Color.DEEPSKYBLUE, Color.BLACK])
    y += 42
    pic.set_pos(LEFT, y).draw_text([f"舰长：", f"{guard:.1f}"], [Color.DEEPSKYBLUE, Color.BLACK])
    y += 42
    pic.set_pos(LEFT, y).draw_text([f"SC：", f"{sc:.1f}"], [Color.DEEPSKYBLUE, Color.BLACK])
    y += 42
    pic.set_pos(LEFT, y).draw_text([f"总计：", f"{total:.1f}"], [Color.DEEPSKYBLUE, Color.BLACK])
    y += 40

    # 版权
    pic.set_pos(W - 260, y + 10)
    pic.draw_text_right(0, "Designed by QianQiuZy", Color.GRAY)

    pic.crop_and_paste_bottom()
    return pic.base64()

# ========================= handlers =========================
@查直播.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    anchor_kw, month_code = _parse_anchor_and_month(str(arg))
    if not anchor_kw:
        await 查直播.finish(MessageSegment.text("用法：/查直播 主播名称 [YYYYMM|YYYY-MM]"))

    logger.info(f"[查直播] kw={anchor_kw} month={month_code} user={getattr(event, 'user_id', 0)}")

    base, match = await _locate_room_by_anchor(anchor_kw)
    if not base or not match:
        await 查直播.finish(MessageSegment.text("未找到用户"))

    anchor_name = str(match.get("anchor_name") or anchor_kw)
    room_id = str(match.get("room_id") or "")
    if not room_id:
        await 查直播.finish(MessageSegment.text("该用户缺少房间信息"))

    try:
        sessions = await query_live_sessions(base=base, room_id=room_id, month_code=month_code)
    except Exception as e:
        await 查直播.finish(MessageSegment.text(f"未能获取直播场次：{e}"))

    b64 = render_live_sessions_image(anchor_name=anchor_name, room_id=room_id, month_code=month_code, sessions=sessions)
    await 查直播.finish(MessageSegment.image(f"base64://{b64}"))


@查SC.handle()
async def _(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    anchor_kw, month_code = _parse_anchor_and_month(str(arg))
    if not anchor_kw:
        await 查SC.finish(MessageSegment.text("用法：/查SC 主播名称 [YYYYMM|YYYY-MM]"))

    logger.info(f"[查SC] kw={anchor_kw} month={month_code} user={getattr(event, 'user_id', 0)}")

    base, match = await _locate_room_by_anchor(anchor_kw)
    if not base or not match:
        await 查SC.finish(MessageSegment.text("未找到用户"))

    anchor_name = str(match.get("anchor_name") or anchor_kw)
    room_id = str(match.get("room_id") or "")
    if not room_id:
        await 查SC.finish(MessageSegment.text("该用户缺少房间信息"))

    try:
        sc_list = await query_sc_list(base=base, room_id=room_id, month_code=month_code)
    except Exception as e:
        await 查SC.finish(MessageSegment.text(f"未能获取 SC 记录：{e}"))

    images = render_sc_images(anchor_name=anchor_name, room_id=room_id, month_code=month_code, sc_list=sc_list)

    # 关键改动：多图 => 合并转发；单图 => 直接发图
    if len(images) <= 1:
        b64 = images[0] if images else ""
        if not b64:
            await 查SC.finish(MessageSegment.text("本月暂无 SC 记录"))
        await 查SC.finish(MessageSegment.image(f"base64://{b64}"))
    else:
        await _send_forward_images(bot, event, title="查SC", images_b64=images, anchor_name=anchor_name)
        await 查SC.finish()

@查流水.handle()
async def _(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, arg: Message = CommandArg()):
    anchor_kw, month_code = _parse_anchor_and_month(str(arg))
    if not anchor_kw:
        await 查流水.finish(MessageSegment.text("用法：/查流水 主播名称 [YYYYMM|YYYY-MM]"))

    # 拉取 VR+PSP 按月合并
    data_list = await fetch_all_data_by_month(month_code)
    if not data_list:
        await 查流水.finish("未找到用户")

    match = next((it for it in data_list if anchor_kw in str(it.get("anchor_name") or "")), None)
    if not match:
        await 查流水.finish("未找到用户")

    b64 = render_liushui_card(
        month_code=month_code,
        anchor=str(match.get("anchor_name") or anchor_kw),
        room_id=match.get("room_id", 0),
        attention=match.get("attention", 0),
        live_duration=str(match.get("live_duration") or "00:00:00"),
        effective_days=match.get("effective_days", 0),
        gift_value=match.get("gift", 0),
        guard_value=match.get("guard", 0),
        sc_value=match.get("super_chat", 0),
    )

    await 查流水.finish(MessageSegment.image(f"base64://{b64}"))
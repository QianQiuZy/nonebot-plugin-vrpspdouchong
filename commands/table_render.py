from __future__ import annotations

import time
from dataclasses import dataclass

from ..toolkit import Color, PicGenerator, timestamp_format

Cell = tuple[str, Color]


@dataclass(frozen=True, slots=True)
class TableRender:
    title: str
    period_display: str
    query_source_text: str
    headers: tuple[str, ...]
    widths: tuple[int, ...]
    rows: list[list[Cell]]
    total_row: tuple[str, ...] | None


def render_table_image(table: TableRender) -> str:
    row_height = 60
    table_width = sum(table.widths) + 40
    table_rows = 1 + len(table.rows) + (1 if table.total_row is not None else 0)
    canvas_height = row_height * table_rows + 250
    pic = PicGenerator(table_width, canvas_height)
    _ = pic.set_pos(0, 0).draw_rounded_rectangle(0, 0, table_width, canvas_height, 0, Color.WHITE)
    _ = pic.set_pos(20, 30).draw_text(table.title, [Color.BLACK])
    now = timestamp_format(int(time.time()), "%Y-%m-%d %H:%M:%S")
    _ = pic.set_pos(20, 90).draw_text(now, [Color.GRAY])
    _ = pic.set_pos(320, 90).draw_text("数据为每月1号开始统计，月底归档。", [Color.GRAY])
    _ = pic.set_pos(20, 120).draw_text(table.query_source_text, [Color.GRAY])
    _ = pic.set_pos(20, 150).draw_text(f"统计周期：{table.period_display}", [Color.GRAY])
    current_y = 190
    _ = pic.draw_rounded_rectangle(20, current_y, table_width - 40, row_height, 0, Color.DEEPSKYBLUE)
    current_x = 30
    for width, header in zip(table.widths, table.headers):
        _ = pic.set_pos(current_x, current_y + 18).draw_text(header, [Color.WHITE])
        current_x += width
    current_y += row_height
    for index, row in enumerate(table.rows):
        background = Color.LIGHTGRAY if index % 2 == 0 else Color.WHITE
        _ = pic.draw_rounded_rectangle(20, current_y, table_width - 40, row_height, 0, background)
        current_x = 30
        for width, (text, color) in zip(table.widths, row):
            _ = pic.set_pos(current_x, current_y + 18).draw_text(text, [color])
            current_x += width
        current_y += row_height
    if table.total_row is not None:
        _ = pic.draw_rounded_rectangle(20, current_y, table_width - 40, row_height, 0, Color.LIGHTGRAY)
        current_x = 30
        for width, text in zip(table.widths, table.total_row):
            _ = pic.set_pos(current_x, current_y + 18).draw_text(text, [Color.BLACK])
            current_x += width
    _ = pic.set_pos(table_width - 220, canvas_height - 60).draw_text_right(0, "Designed by 开发猫", Color.GRAY)
    return pic.base64()

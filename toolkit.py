# src/plugins/vr_gift/toolkit.py
from __future__ import annotations

import base64
import time
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple, Union, Iterable
import unicodedata

from PIL import Image, ImageDraw, ImageFont


def timestamp_format(timestamp: int, format_str: str) -> str:
    """时间戳格式化"""
    return time.strftime(format_str, time.localtime(timestamp))


class Color(Enum):
    """常用颜色 RGB 枚举（保留本插件常用项；需要更多再补）"""
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    GRAY = (169, 169, 169)
    LIGHTGRAY = (244, 244, 244)
    DEEPSKYBLUE = (0, 191, 255)


_RGB = Tuple[int, int, int]


def _to_rgb(color: Union[Color, _RGB]) -> _RGB:
    return color.value if isinstance(color, Color) else color


def _text_length(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    """
    Pillow 版本差异兼容：
    - 优先用 draw.textlength
    - 再退回 font.getlength
    - 最后退回 draw.textbbox
    """
    try:
        return int(draw.textlength(text, font))
    except Exception:
        pass
    try:
        return int(font.getlength(text))  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return int(right - left)
    except Exception:
        return len(text) * 10

def _is_emoji_char(ch: str) -> bool:
    """
    工程化判定：覆盖常见 emoji 区间 + 变体选择符/ZWJ
    不追求 100% Unicode 完整性，但足够应对昵称/文本中的 emoji。
    """
    if not ch:
        return False
    o = ord(ch)

    # Variation Selector-16 / ZWJ：用于 emoji 序列
    if o in (0xFE0F, 0x200D):
        return True

    # 常见 emoji blocks
    if 0x1F300 <= o <= 0x1FAFF:  # Misc Symbols & Pictographs, Emoticons, Transport, Supplemental, Symbols& Pictographs Ext-A
        return True
    if 0x2600 <= o <= 0x27BF:    # Misc symbols / Dingbats
        return True
    if 0x1F1E6 <= o <= 0x1F1FF:  # Regional indicator (flags)
        return True

    # 兜底：某些 emoji 可能落在其他范围，保守处理
    cat = unicodedata.category(ch)
    return cat in {"So"}  # Symbol, other


def _split_runs_by_emoji(s: str) -> Iterable[Tuple[str, bool]]:
    """
    将字符串拆成若干 run：
      - run_text
      - run_is_emoji（该 run 使用 emoji 字体）
    处理 VS16/ZWJ 序列：尽量将其归并到相邻 emoji run 中。
    """
    if not s:
        return

    buf = []
    buf_is_emoji = False

    def flush():
        nonlocal buf
        if buf:
            yield ("".join(buf), buf_is_emoji)
            buf = []

    i = 0
    while i < len(s):
        ch = s[i]
        is_e = _is_emoji_char(ch)

        # VS16/ZWJ 视为“附着符号”，尽量并入前一个 run
        if ord(ch) in (0xFE0F, 0x200D):
            if buf:
                buf.append(ch)
            else:
                buf = [ch]
                buf_is_emoji = True
            i += 1
            continue

        if not buf:
            buf = [ch]
            buf_is_emoji = is_e
        else:
            if is_e == buf_is_emoji:
                buf.append(ch)
            else:
                # 切 run
                for out in flush():
                    yield out
                buf = [ch]
                buf_is_emoji = is_e

        i += 1

    for out in flush():
        yield out

class PicGenerator:
    """
    基于 Pillow 的绘图器（裁剪版）
    - 去掉外部 config 依赖
    - 字体由 resource_dir + 字体文件名确定
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        resource_dir: Optional[Union[str, Path]] = None,
        normal_font: str = "NotoSansSC.ttf",
        bold_font: str = "NotoSansSC.ttf",
        emoji_font: str = "NotoEmoji.ttf",
        auto_size_margin: int = 10,
    ):
        self.__width = int(width)
        self.__height = int(height)

        self.__canvas = Image.new("RGBA", (self.__width, self.__height))
        self.__draw = ImageDraw.Draw(self.__canvas)

        # 资源路径：默认与 toolkit.py 同目录的 resource/
        base = Path(resource_dir) if resource_dir else (Path(__file__).resolve().parent / "resource")
        normal_path = base / normal_font
        bold_path = base / bold_font
        emoji_path = base / emoji_font
        if not emoji_path.exists():
            raise FileNotFoundError(f"Emoji 字体缺失：{emoji_path}")
        # 你的场景需要中文字体，建议明确提供字体；缺失时抛错更早暴露问题
        if not normal_path.exists() or not bold_path.exists():
            raise FileNotFoundError(
                f"字体文件缺失：normal={normal_path} bold={bold_path}；请将字体放入 resource/ 或传入 resource_dir"
            )
        self.__emoji_font = ImageFont.truetype(str(emoji_path), 30)
        self.__chapter_font = ImageFont.truetype(str(bold_path), 50)
        self.__section_font = ImageFont.truetype(str(bold_path), 40)
        self.__tip_font = ImageFont.truetype(str(normal_path), 25)
        self.__text_font = ImageFont.truetype(str(normal_path), 30)

        self.__xy = (0, 0)
        self.__row_space = 25
        self.__bottom_pic: Optional[Image.Image] = None
        self.__auto_size_margin = int(auto_size_margin)

    # ------------------ 基础属性 ------------------
    @property
    def width(self) -> int:
        return self.__width

    @property
    def height(self) -> int:
        return self.__height

    @property
    def x(self) -> int:
        return self.__xy[0]

    @property
    def y(self) -> int:
        return self.__xy[1]

    @property
    def xy(self) -> Tuple[int, int]:
        return self.__xy

    # ------------------ 坐标控制 ------------------
    def set_row_space(self, row_space: int) -> "PicGenerator":
        self.__row_space = int(row_space)
        return self

    def set_pos(self, x: Optional[int] = None, y: Optional[int] = None) -> "PicGenerator":
        self.__xy = (self.x if x is None else int(x), self.y if y is None else int(y))
        return self

    def move_pos(self, x: int, y: int) -> "PicGenerator":
        self.__xy = (self.x + int(x), self.y + int(y))
        return self

    # ------------------ 裁剪/底部处理 ------------------
    def copy_bottom(self, height: int) -> "PicGenerator":
        h = int(height)
        self.__bottom_pic = self.__canvas.crop((0, self.height - h, self.width, self.height))
        return self

    def crop_and_paste_bottom(self) -> "PicGenerator":
        if self.__bottom_pic is None:
            self.__canvas = self.__canvas.crop((0, 0, self.width, self.y))
            self.__draw = ImageDraw.Draw(self.__canvas)
            return self

        bottom = self.__bottom_pic
        self.__canvas = self.__canvas.crop((0, 0, self.width, self.y + bottom.height))
        self.__canvas.paste(bottom, (0, self.y))
        self.__draw = ImageDraw.Draw(self.__canvas)
        bottom.close()
        self.__bottom_pic = None
        return self

    def _draw_with_fallback(self, x: int, y: int, text: str, rgb: _RGB) -> int:
        """
        绘制 text 到 (x,y)，返回绘制宽度（用于 x 累加）。
        emoji run 使用 emoji 字体，其余使用中文字体。
        """
        used_width = 0
        for run_text, run_is_emoji in _split_runs_by_emoji(text):
            font = self.__emoji_font if run_is_emoji else self.__text_font
            self.__draw.text((x + used_width, y), run_text, rgb, font)
            used_width += _text_length(self.__draw, run_text, font)
        return used_width

    def _measure_with_fallback(self, text: str) -> int:
        """计算 text 在 fallback 字体策略下的绘制宽度，用于右对齐等场景。"""
        total = 0
        for run_text, run_is_emoji in _split_runs_by_emoji(text):
            font = self.__emoji_font if run_is_emoji else self.__text_font
            total += _text_length(self.__draw, run_text, font)
        return total

    # ------------------ 图形 ------------------
    def draw_rounded_rectangle(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        radius: int,
        color: Union[Color, _RGB],
    ) -> "PicGenerator":
        self.__draw.rounded_rectangle(
            ((int(x), int(y)), (int(x + width), int(y + height))),
            int(radius),
            _to_rgb(color),
        )
        return self

    # ------------------ 文本 ------------------
    def draw_text(
        self,
        texts: Union[str, List[str]],
        colors: Optional[Union[Color, _RGB, List[Union[Color, _RGB]]]] = None,
        xy: Optional[Tuple[int, int]] = None,
    ) -> "PicGenerator":
        if isinstance(texts, str):
            texts_list = [texts]
        else:
            texts_list = list(texts)

        if colors is None:
            colors_list: List[Union[Color, _RGB]] = []
        elif isinstance(colors, (Color, tuple)):
            colors_list = [colors]
        else:
            colors_list = list(colors)

        # 补齐颜色
        while len(colors_list) < len(texts_list):
            colors_list.append(Color.BLACK)

                # 统一转 rgb
        rgb_list: List[_RGB] = [_to_rgb(c) for c in colors_list[: len(texts_list)]]

        if xy is None:
            base_x = self.x
            for i, t in enumerate(texts_list):
                rgb = rgb_list[i]
                w = self._draw_with_fallback(self.x, self.y, t, rgb)  # ✅
                self.move_pos(w, 0)
            self.set_pos(base_x, self.y + self.__text_font.size + self.__row_space)
        else:
            x, y = int(xy[0]), int(xy[1])
            for i, t in enumerate(texts_list):
                rgb = rgb_list[i]
                w = self._draw_with_fallback(x, y, t, rgb)  # ✅
                x += w

        return self

    def draw_text_right(
        self,
        margin_right: int,
        texts: Union[str, List[str]],
        colors: Optional[Union[Color, _RGB, List[Union[Color, _RGB]]]] = None,
        xy_limit: Tuple[int, int] = (0, 0),
    ) -> "PicGenerator":
        # 右对齐字符串

        text_joined = texts if isinstance(texts, str) else "".join(texts)
        text_len = self._measure_with_fallback(text_joined)  # ✅ 替换原 _text_length(self.__draw,...)
        x = self.width - int(margin_right) - text_len

        # 防覆盖点：按你的原逻辑保留 margin
        limit_x = int(xy_limit[0]) - self.__auto_size_margin
        limit_y = int(xy_limit[1]) + self.__auto_size_margin
        y = max(self.y, limit_y)

        self.draw_text(texts, colors, (x, y))
        self.set_pos(self.x, y + self.__text_font.size + self.__row_space)
        return self

    # ------------------ 输出 ------------------
    def base64(self) -> str:
        io = BytesIO()
        self.__canvas.save(io, format="PNG")
        self.__canvas.close()
        return base64.b64encode(io.getvalue()).decode()

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="vr_gift",
    description="VR/PSP 礼物统计指令集合（斗虫）",
    usage="/VR斗虫 [YYYYMM|YYYY-MM]\n/PSP斗虫 [YYYYMM|YYYY-MM]",
    config=Config,
)

from .commands import douchong as _douchong  # noqa: F401
from .commands import live_list as _live_list  # noqa: F401
from .commands import query as _query  # noqa: F401

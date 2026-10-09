"""Process-wide pacing for this plugin's ordinary image messages."""

from __future__ import annotations

from asyncio import Lock, sleep
from time import monotonic
from typing import Any, NoReturn

from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.internal.matcher import Matcher

_IMAGE_INTERVAL = 0.3


class _ImageLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_send_at = 0.0

    async def wait(self) -> None:
        # Only serialize request starts, without waiting for QQ's response.
        async with self._lock:
            while True:
                now = monotonic()
                delay = self._next_send_at - now
                if delay <= 0:
                    self._next_send_at = now + _IMAGE_INTERVAL
                    return
                await sleep(delay)


_limiter = _ImageLimiter()


async def _wait_for_image(message: str | Message | MessageSegment) -> None:
    if any(segment.type == "image" for segment in Message(message)):
        await _limiter.wait()


async def send(
    bot: Bot,
    event: MessageEvent,
    message: str | Message | MessageSegment,
    **kwargs: Any,
) -> Any:
    await _wait_for_image(message)
    return await bot.send(event, message, **kwargs)


async def finish(
    matcher: type[Matcher],
    message: str | Message | MessageSegment,
    **kwargs: Any,
) -> NoReturn:
    await _wait_for_image(message)
    await matcher.finish(message, **kwargs)

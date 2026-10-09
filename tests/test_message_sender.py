from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from time import monotonic

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.exception import FinishedException

_SPEC = importlib.util.spec_from_file_location(
    "vrpsp_message_sender_tests", Path(__file__).resolve().parents[1] / "message_sender.py"
)
assert _SPEC is not None and _SPEC.loader is not None
sender = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sender)


@pytest.fixture(autouse=True)
def reset_limiter(monkeypatch):
    monkeypatch.setattr(sender, "_limiter", sender._ImageLimiter())


@pytest.fixture
def virtual_clock(monkeypatch):
    now = [100.0]
    delays = []

    async def sleep(delay):
        delays.append(delay)
        now[0] += delay

    monkeypatch.setattr(sender, "monotonic", lambda: now[0])
    monkeypatch.setattr(sender, "sleep", sleep)
    return now, delays


class _Bot:
    def __init__(self, starts=None):
        self.starts = starts if starts is not None else []
        self.calls = []

    async def send(self, event, message, **kwargs):
        self.starts.append(sender.monotonic())
        self.calls.append((event, message, kwargs))
        return {"message_id": len(self.calls)}


def test_concurrent_bots_events_and_matchers_share_one_interval():
    starts = []

    class Matcher:
        @classmethod
        async def finish(cls, message, **kwargs):
            starts.append(monotonic())
            raise FinishedException

    async def finish():
        with pytest.raises(FinishedException):
            await sender.finish(Matcher, MessageSegment.image("base64://image"))

    async def run():
        first, second = _Bot(starts), _Bot(starts)
        await asyncio.gather(
            sender.send(first, "group-1", MessageSegment.image("base64://image")),
            sender.send(second, "group-2", MessageSegment.image("base64://image")),
            sender.send(first, "private-1", MessageSegment.image("file:///image.png")),
            finish(),
        )

    asyncio.run(run())
    assert len(starts) == 4
    assert all(later - earlier >= 0.3 - 0.001 for earlier, later in zip(starts, starts[1:]))


def test_first_image_is_immediate_and_arguments_and_result_are_preserved(virtual_clock):
    _, delays = virtual_clock
    bot = _Bot()
    event = object()
    image = MessageSegment.image("base64://image")

    async def run():
        assert await sender.send(bot, event, image, at_sender=True) == {"message_id": 1}

    asyncio.run(run())
    assert delays == []
    assert bot.calls == [(event, image, {"at_sender": True})]


def test_text_and_forward_messages_do_not_wait_or_consume_image_slot(virtual_clock):
    now, delays = virtual_clock
    bot = _Bot()

    async def run():
        await sender.send(bot, "group", MessageSegment.image("base64://first"))
        await sender.send(bot, "group", "普通文字")
        await sender.send(bot, "group", MessageSegment.forward("forward-id"))
        assert delays == []
        # A message containing text plus an image still needs pacing.
        await sender.send(bot, "group", Message("说明") + MessageSegment.image("base64://second"))

    asyncio.run(run())
    assert bot.starts == pytest.approx([100.0, 100.0, 100.0, 100.3])
    assert now[0] == pytest.approx(100.3)


def test_finish_preserves_matcher_termination_and_skips_text(virtual_clock):
    _, delays = virtual_clock
    calls = []

    class Matcher:
        @classmethod
        async def finish(cls, message, **kwargs):
            calls.append((message, kwargs))
            raise FinishedException

    image = MessageSegment.image("base64://image")

    async def run():
        for message in (image, "文字", image):
            with pytest.raises(FinishedException):
                await sender.finish(Matcher, message, at_sender=True)

    asyncio.run(run())
    assert calls == [(image, {"at_sender": True}), ("文字", {"at_sender": True}), (image, {"at_sender": True})]
    assert delays == pytest.approx([0.3])


def test_failed_image_send_is_paced_without_automatic_retry(virtual_clock):
    _, delays = virtual_clock
    error = ActionFailed(status="failed", retcode=1200, data=None)

    class FailingBot(_Bot):
        async def send(self, event, message, **kwargs):
            await super().send(event, message, **kwargs)
            raise error

    bot = FailingBot()
    following = _Bot()

    async def run():
        with pytest.raises(ActionFailed) as caught:
            await sender.send(bot, "group", MessageSegment.image("base64://image"))
        assert caught.value is error
        await sender.send(following, "group", MessageSegment.image("base64://next"))

    asyncio.run(run())
    assert len(bot.calls) == 1
    assert delays == pytest.approx([0.3])


def test_slow_response_does_not_hold_the_queue():
    starts = []

    async def run():
        release = asyncio.Event()
        started = asyncio.Event()

        class SlowBot(_Bot):
            async def send(self, event, message, **kwargs):
                result = await super().send(event, message, **kwargs)
                started.set()
                await release.wait()
                return result

        first = asyncio.create_task(sender.send(SlowBot(starts), "group", MessageSegment.image("base64://first")))
        await started.wait()
        try:
            await asyncio.wait_for(
                sender.send(_Bot(starts), "private", MessageSegment.image("base64://second")),
                timeout=2,
            )
            assert not first.done()
        finally:
            release.set()
            await first

    asyncio.run(run())
    assert starts[1] - starts[0] >= 0.3 - 0.001


def test_cancelling_queued_image_does_not_block_following_images():
    async def run():
        bot = _Bot()
        image = MessageSegment.image("base64://image")
        await sender.send(bot, "group", image)
        queued = asyncio.create_task(sender.send(bot, "group", image))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        await asyncio.wait_for(sender.send(bot, "private", image), timeout=2)
        assert len(bot.calls) == 2
        assert bot.starts[1] - bot.starts[0] >= 0.3 - 0.001

    asyncio.run(run())

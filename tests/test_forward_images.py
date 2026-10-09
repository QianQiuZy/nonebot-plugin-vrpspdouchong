from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import anyio
import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.exception import FinishedException

nonebot.init()

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_NAME = "nonebot_plugin_vrpspdouchong"
_PACKAGE_SPEC = importlib.util.spec_from_file_location(
    _PACKAGE_NAME,
    _PACKAGE_ROOT / "__init__.py",
    submodule_search_locations=[str(_PACKAGE_ROOT)],
)
assert _PACKAGE_SPEC is not None and _PACKAGE_SPEC.loader is not None
_PACKAGE = importlib.util.module_from_spec(_PACKAGE_SPEC)
sys.modules[_PACKAGE_NAME] = _PACKAGE
_PACKAGE_SPEC.loader.exec_module(_PACKAGE)

douchong = importlib.import_module(f"{_PACKAGE_NAME}.commands.douchong")
query = importlib.import_module(f"{_PACKAGE_NAME}.commands.query")
sender = importlib.import_module(f"{_PACKAGE_NAME}.message_sender")
live_list = importlib.import_module(f"{_PACKAGE_NAME}.commands.live_list")


@pytest.fixture(autouse=True)
def reset_image_limiter(monkeypatch):
    monkeypatch.setattr(sender, "_limiter", sender._ImageLimiter())


class _Event:
    group_id = 123


class _PrivateEvent:
    user_id = 789


class _Bot:
    self_id = "456"

    def __init__(self) -> None:
        self.messages = []

    async def call_api(self, action: str, **kwargs: object) -> dict[str, int] | None:
        self.messages.append((action, kwargs))
        if action == "send_private_msg":
            return {"message_id": 9001}
        return None

    async def send(self, event: _Event, message: MessageSegment) -> None:
        self.messages.append(("send", {"event": event, "message": message}))


@pytest.mark.parametrize("private", [False, True])
def test_forward_nodes_reference_preuploaded_messages_for_napcat(tmp_path: Path, monkeypatch, private: bool) -> None:
    image_path = tmp_path / "detail.png"
    image_path.write_bytes(b"png-data")
    monkeypatch.setattr(query, "GroupMessageEvent", _Event)
    monkeypatch.setattr(query, "PrivateMessageEvent", _PrivateEvent)

    async def must_not_wait():
        pytest.fail("Forward messages and their preuploads must bypass image pacing")

    monkeypatch.setattr(sender._limiter, "wait", must_not_wait)

    async def run() -> None:
        bot = _Bot()
        await query._send_forward_images(
            bot,
            _PrivateEvent() if private else _Event(),
            title="查直播详细",
            image_paths=[image_path],
            anchor_name="主播A",
            item_label="场",
        )
        upload_action, upload_kwargs = bot.messages[0]
        assert upload_action == "send_private_msg"
        upload_content = Message(upload_kwargs["message"])
        image_segment = next(segment for segment in upload_content if segment.type == "image")
        assert image_segment.data["file"].startswith("base64://")

        forward_action, forward_kwargs = bot.messages[1]
        assert forward_action == ("send_private_forward_msg" if private else "send_forward_msg")
        nodes = forward_kwargs["messages"]
        assert nodes[1].type == "node"
        assert nodes[1].data["id"] == "9001"

    anyio.run(run)


def test_douchong_sends_both_charts_as_one_forward_message(tmp_path: Path, monkeypatch) -> None:
    forwarded: list[tuple[str, list[Path], str]] = []

    def save_image(
        image_b64: str,
        *,
        anchor_name: str,
        page_no: int,
        total_pages: int,
    ) -> Path:
        image_path = tmp_path / f"{page_no}-{total_pages}.png"
        image_path.write_text(image_b64)
        return image_path

    async def send_forward(
        bot: _Bot,
        event: _Event,
        *,
        title: str,
        image_paths: list[Path],
        anchor_name: str = "",
        item_label: str = "页",
    ) -> None:
        forwarded.append((title, image_paths, item_label))

    monkeypatch.setattr(douchong, "_save_sc_image_file", save_image)
    monkeypatch.setattr(douchong, "_send_forward_images", send_forward)

    async def run() -> None:
        await douchong.send_douchong_images(
            _Bot(),
            _Event(),
            title="VR斗虫",
            period_display="2026-09",
            images=["chart-1", "chart-2"],
        )

    anyio.run(run)

    assert len(forwarded) == 1
    assert forwarded[0][0] == "VR斗虫"
    assert [path.read_text() for path in forwarded[0][1]] == ["chart-1", "chart-2"]
    assert forwarded[0][2] == "张"


def test_douchong_sends_one_chart_as_a_normal_image(monkeypatch) -> None:
    saved_images: list[str] = []
    forwarded: list[list[Path]] = []

    def save_image(
        image_b64: str,
        *,
        anchor_name: str,
        page_no: int,
        total_pages: int,
    ) -> Path:
        saved_images.append(image_b64)
        return Path(f"{anchor_name}-{page_no}-{total_pages}.png")

    async def send_forward(
        bot: object,
        event: object,
        *,
        title: str,
        image_paths: list[Path],
        anchor_name: str = "",
        item_label: str = "页",
    ) -> None:
        forwarded.append(image_paths)

    monkeypatch.setattr(douchong, "_save_sc_image_file", save_image)
    monkeypatch.setattr(douchong, "_send_forward_images", send_forward)
    waits = []

    async def wait():
        waits.append(True)

    monkeypatch.setattr(sender._limiter, "wait", wait)

    async def run() -> _Bot:
        bot = _Bot()
        await douchong.send_douchong_images(
            bot,
            _Event(),
            title="VR斗虫",
            period_display="2026-08",
            images=["chart-1"],
        )
        return bot

    bot = anyio.run(run)

    assert saved_images == []
    assert forwarded == []
    assert waits == [True]
    action, kwargs = bot.messages[0]
    assert action == "send"
    content = Message(kwargs["message"])
    image_segment = next(segment for segment in content if segment.type == "image")
    assert image_segment.data["file"] == "base64://chart-1"


def test_live_list_commands_and_douchong_share_image_pacing(monkeypatch) -> None:
    now = [100.0]
    starts = []

    async def sleep(delay):
        now[0] += delay

    async def handle_live_list(**kwargs):
        return MessageSegment.image("base64://live-list")

    async def send(message, **kwargs):
        starts.append(now[0])

    class Bot(_Bot):
        async def send(self, event, message):
            starts.append(now[0])
            await super().send(event, message)

    monkeypatch.setattr(sender, "monotonic", lambda: now[0])
    monkeypatch.setattr(sender, "sleep", sleep)
    monkeypatch.setattr(live_list, "_handle_live_list", handle_live_list)
    monkeypatch.setattr(live_list, "_handle_live_list_brawl", handle_live_list)
    matchers = (live_list.VR开播, live_list.PSP开播, live_list.大乱斗开播)
    for matcher in matchers:
        monkeypatch.setattr(matcher, "send", send)

    async def run():
        for matcher in matchers:
            with pytest.raises(FinishedException):
                await matcher.handlers[0].call(event=_Event())
        await douchong.send_douchong_images(
            Bot(), _PrivateEvent(), title="VR斗虫", period_display="2026-10", images=["chart"]
        )

    anyio.run(run)
    assert starts == pytest.approx([100.0, 100.3, 100.6, 100.9])

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import anyio
import nonebot

nonebot.init()

from nonebot.adapters.onebot.v11 import Message

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


class _Event:
    group_id = 123


class _Bot:
    self_id = "456"

    def __init__(self) -> None:
        self.messages = []

    async def call_api(self, action: str, **kwargs: object) -> dict[str, int] | None:
        self.messages.append((action, kwargs))
        if action == "send_private_msg":
            return {"message_id": 9001}
        return None


def test_forward_nodes_reference_preuploaded_messages_for_napcat(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "detail.png"
    image_path.write_bytes(b"png-data")
    monkeypatch.setattr(query, "GroupMessageEvent", _Event)

    async def run() -> None:
        bot = _Bot()
        await query._send_forward_images(
            bot,
            _Event(),
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
        assert forward_action == "send_forward_msg"
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
        bot: object,
        event: object,
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

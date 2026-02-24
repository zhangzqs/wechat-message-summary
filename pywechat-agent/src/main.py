"""pywechat-agent 主程序入口：pyweixin 轮询微信消息 → NATS JetStream 发布

不使用 pyweixin 的 Monitor.listen_on_chat()（返回汇总数据，丢失逐条消息上下文），
而是借鉴其底层轮询逻辑，直接从 UI 元素中逐条提取 sender + content + type。

线程模型：
- 主线程：pyweixin 窗口管理 + while True 轮询循环
- 守护线程：asyncio 事件循环，处理 NATS 异步发布
- 桥接方式：asyncio.run_coroutine_threadsafe
"""

import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path

import nats
from nats.js import JetStreamContext

from config import ChatTransferConfig, load_config_from_args
from logger import init_logger
from message import build_payload

logger = logging.getLogger("pywechat-agent")


def _ensure_pyweixin_importable() -> None:
    """确保 vendor/pywechat/pyweixin 在 sys.path 中，使 pyweixin 可导入。

    pyweixin 未发布到 PyPI，需要通过 git submodule 或直接拷贝到 vendor/ 目录。
    """
    vendor_path = Path(__file__).resolve().parent.parent / "vendor" / "pywechat"
    if vendor_path.is_dir() and str(vendor_path) not in sys.path:
        sys.path.insert(0, str(vendor_path))
        logger.debug("已将 pyweixin 路径加入 sys.path: %s", vendor_path)


def _run_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """在独立守护线程中运行 asyncio 事件循环。

    pyweixin 的轮询循环在主线程阻塞运行，NATS 的 asyncio 事件循环
    必须在单独的线程中持续运行，以处理 run_coroutine_threadsafe 提交的协程。
    """
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _publish_message(
    loop: asyncio.AbstractEventLoop,
    js: JetStreamContext,
    transfer: ChatTransferConfig,
    text: str,
    class_name: str,
) -> None:
    """将单条消息构建为 payload 并异步发布到 NATS。"""

    async def _async_publish() -> None:
        payload = build_payload(
            text=text,
            class_name=class_name,
            chat_name=transfer.chat,
        )
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            ack = await js.publish(transfer.subject, data)
            logger.info(
                "已发布消息到 %s (stream=%s, seq=%d): sender=%s, type=%s",
                transfer.subject,
                ack.stream,
                ack.seq,
                payload["sender"],
                payload["type"],
            )
        except Exception:
            logger.exception("发布消息到 NATS 失败: subject=%s", transfer.subject)

    future = asyncio.run_coroutine_threadsafe(_async_publish(), loop)
    try:
        future.result(timeout=10)
    except Exception:
        logger.exception("异步发布桥接超时或失败")


def _poll_new_messages(
    tracker: dict,
    loop: asyncio.AbstractEventLoop,
    js: JetStreamContext,
) -> None:
    """检查单个会话窗口中是否有新消息，有则逐条发布到 NATS。

    轮询逻辑参考 pyweixin 源码 Monitor.listen_on_chat 的底层实现：
    通过 chatList 的 ListItem children 的 runtime_id 检测新消息。
    """
    try:
        chat_list = tracker["chat_list"]
        items = chat_list.children(control_type="ListItem")
    except Exception:
        logger.debug("获取 %s 的消息列表失败，跳过本轮", tracker["transfer"].chat)
        return

    if not items:
        return

    last_rid = tracker["last_rid"]
    new_items: list = []
    found_last = False

    # 从最旧到最新遍历，找到 last_rid 之后的所有新消息
    for item in items:
        rid = item.element_info.runtime_id
        if found_last:
            new_items.append(item)
        elif rid == last_rid:
            found_last = True

    # 如果没找到 last_rid（窗口消息已滚动太远），取最后一条作为增量
    if not found_last and items:
        new_items = [items[-1]]

    for item in new_items:
        try:
            class_name = item.class_name()
            text = item.window_text()
        except Exception:
            logger.debug("读取消息 UI 元素属性失败，跳过")
            continue

        if not text:
            continue

        _publish_message(loop, js, tracker["transfer"], text, class_name)

    # 更新 tracker 的 last_rid
    if items:
        tracker["last_rid"] = items[-1].element_info.runtime_id


def main() -> None:
    """主入口：启动 asyncio 事件循环线程 → 连接 NATS → 初始化 pyweixin → 轮询监听。"""
    cfg = load_config_from_args()
    init_logger(cfg.logger)

    if not cfg.chat_transfer_config:
        logger.warning("chat_transfer_config 为空，没有需要监听的会话")
        return

    # --- 创建并启动 asyncio 事件循环（独立线程）---
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=_run_event_loop, args=(loop,), daemon=True)
    loop_thread.start()

    # --- NATS 连接（在事件循环线程中执行）---
    logger.info("正在连接 NATS: %s", cfg.nats_url)
    nc = asyncio.run_coroutine_threadsafe(
        nats.connect(cfg.nats_url), loop
    ).result(timeout=10)
    js = nc.jetstream()
    logger.info("NATS JetStream 连接成功")

    # --- pyweixin 初始化（延迟导入，仅 Windows 可用）---
    _ensure_pyweixin_importable()
    try:
        from pyweixin import Navigator  # type: ignore[import-untyped]
        from pyweixin.Uielements import Lists  # type: ignore[import-untyped]
    except ImportError:
        logger.error(
            "pyweixin 库导入失败，请确认：\n"
            "  1. 运行在 Windows 环境\n"
            "  2. vendor/pywechat/ 目录包含 pyweixin 源码\n"
            "  3. 已安装 pywinauto/pyautogui/pywin32/comtypes 依赖"
        )
        loop.call_soon_threadsafe(loop.stop)
        return

    # --- 为每个会话打开独立对话窗口 ---
    trackers: dict[str, dict] = {}
    for transfer in cfg.chat_transfer_config:
        logger.info("正在打开会话窗口: %s", transfer.chat)
        try:
            win = Navigator.open_seperate_dialog_window(
                friend=transfer.chat,
                window_minimize=cfg.window_minimize,
                close_weixin=True,
            )
        except Exception:
            logger.exception("打开会话窗口失败: %s", transfer.chat)
            continue

        try:
            chat_list = win.child_window(**Lists.FriendChatList)
            items = chat_list.children(control_type="ListItem")
            last_rid = items[-1].element_info.runtime_id if items else 0
        except Exception:
            logger.exception("初始化消息列表失败: %s", transfer.chat)
            last_rid = 0
            chat_list = win.child_window(**Lists.FriendChatList)

        trackers[transfer.chat] = {
            "window": win,
            "transfer": transfer,
            "chat_list": chat_list,
            "last_rid": last_rid,
        }
        logger.info(
            "已初始化监听: chat=%s → subject=%s",
            transfer.chat,
            transfer.subject,
        )

    if not trackers:
        logger.error("没有成功打开任何会话窗口，程序退出")
        asyncio.run_coroutine_threadsafe(nc.drain(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        return

    # --- 主轮询循环 ---
    logger.info("所有监听已就绪（共 %d 个会话），开始轮询...", len(trackers))
    try:
        while True:
            for _chat, tracker in trackers.items():
                _poll_new_messages(tracker, loop, js)
            time.sleep(cfg.poll_interval)
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    finally:
        asyncio.run_coroutine_threadsafe(nc.drain(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        logger.info("NATS 连接已关闭，程序退出")


if __name__ == "__main__":
    main()

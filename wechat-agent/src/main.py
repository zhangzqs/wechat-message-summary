"""wechat-agent 主程序入口：wxauto 监听微信消息 → NATS JetStream 发布"""

import asyncio
import json
import logging
import threading
import uuid

import nats
from nats.js import JetStreamContext

from config import ChatTransferConfig, load_config_from_args
from logger import init_logger

logger = logging.getLogger("wechat-agent")

# wxauto 消息类名 → Go 端 MessageAttr 枚举值
_MSG_ATTR_MAP: dict[str, str] = {
    "FriendMessage": "friend",
    "SelfMessage": "self",
    "SystemMessage": "system",
    "TickleMessage": "tickle",
    "TimeMessage": "time",
}


def _resolve_msg_attr(msg: object) -> str:
    """根据 wxauto 消息对象的类名映射到 Go 端的 MessageAttr 枚举值。"""
    class_name = type(msg).__name__
    return _MSG_ATTR_MAP.get(class_name, "other")


def _resolve_msg_type(msg: object) -> str:
    """从 wxauto 消息对象中提取消息内容类型（text/image/...），缺省为 text。"""
    return getattr(msg, "type", "text") or "text"


def _build_payload(msg: object, chat_name: str) -> dict:
    """将 wxauto 消息对象转为与 Go 端 ReceivedMessage 契约一致的 dict。"""
    return {
        "id": f"msg_{uuid.uuid4().hex[:16]}",
        "type": _resolve_msg_type(msg),
        "attr": _resolve_msg_attr(msg),
        "content": getattr(msg, "content", "") or "",
        "sender": getattr(msg, "sender", "") or "",
        "sender_remark": getattr(msg, "sender_remark", "") or "",
        "info": {
            "chat_type": "friend",  # 默认值，wxauto 无法直接区分
            "chat_name": chat_name,
        },
    }


def _make_sync_callback(
    loop: asyncio.AbstractEventLoop,
    js: JetStreamContext,
    transfer: ChatTransferConfig,
) -> callable:
    """为每个监听会话生成同步回调函数，内部桥接到 asyncio 事件循环发布 NATS 消息。

    wxauto 的回调在其内部轮询线程中同步调用，而 NATS 客户端是 asyncio 驱动的。
    通过 asyncio.run_coroutine_threadsafe 将协程安全地提交到运行在独立线程中的事件循环。
    """

    async def _async_publish(msg: object, chat: str) -> None:
        payload = _build_payload(msg, chat)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            ack = await js.publish(transfer.subject, data)
            logger.info(
                "已发布消息到 %s (stream=%s, seq=%d): sender=%s, attr=%s",
                transfer.subject,
                ack.stream,
                ack.seq,
                payload["sender"],
                payload["attr"],
            )
        except Exception:
            logger.exception("发布消息到 NATS 失败: subject=%s", transfer.subject)

    def _sync_callback(msg: object, chat: str) -> None:
        """wxauto 同步回调 → asyncio 异步发布桥接"""
        future = asyncio.run_coroutine_threadsafe(_async_publish(msg, chat), loop)
        try:
            future.result(timeout=10)
        except Exception:
            logger.exception("同步回调桥接异步发布超时或失败")

    return _sync_callback


def _run_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """在独立守护线程中运行 asyncio 事件循环。

    wxauto 的 KeepRunning() 会阻塞主线程，因此 NATS 的 asyncio 事件循环
    必须在单独的线程中持续运行，以处理 run_coroutine_threadsafe 提交的协程。
    """
    asyncio.set_event_loop(loop)
    loop.run_forever()


def main() -> None:
    """主入口：启动 asyncio 事件循环线程 → 连接 NATS → 初始化 wxauto → 阻塞监听。"""
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
    nc = asyncio.run_coroutine_threadsafe(nats.connect(cfg.nats_url), loop).result(timeout=10)
    js = nc.jetstream()
    logger.info("NATS JetStream 连接成功")

    # --- wxauto 初始化（延迟导入，仅 Windows 可用）---
    try:
        from wxauto import WeChat  # type: ignore[import-untyped]
    except ImportError:
        logger.error("wxauto 库导入失败，请确认运行在 Windows 环境且已安装 wxauto")
        loop.call_soon_threadsafe(loop.stop)
        return

    wx = WeChat()
    logger.info("wxauto WeChat 实例初始化成功")

    # --- 注册监听会话 ---
    for transfer in cfg.chat_transfer_config:
        callback = _make_sync_callback(loop, js, transfer)
        wx.AddListenChat(nickname=transfer.chat, callback=callback)
        logger.info("已注册监听: chat=%s → subject=%s", transfer.chat, transfer.subject)

    # --- 阻塞主线程，wxauto 轮询运行 ---
    logger.info("所有监听已就绪，开始运行...")
    try:
        wx.KeepRunning()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    finally:
        asyncio.run_coroutine_threadsafe(nc.drain(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        logger.info("NATS 连接已关闭，程序退出")


if __name__ == "__main__":
    main()

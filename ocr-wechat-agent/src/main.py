"""ocr-wechat-agent 主程序

架构：
- 主线程（STA COM）：截图 → OCR → 差分检测 → 发布到 NATS（轮询循环）
- 守护线程：asyncio 事件循环，处理 NATS 异步发布

新消息检测算法（锚定差分）：
  每轮扫描后保留最后 anchor_lines 行作为"锚"，
  下轮扫描时在新结果中定位该锚，锚之后的行即为新消息。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field

import nats
import pythoncom  # type: ignore[import-untyped]
from PIL import Image
from nats.js import JetStreamContext

from config import ChatTransferConfig, Config, load_config_from_args
from logger import init_logger
from ocr_engine import OcrLine, recognize
from wechat_window import (
    crop_message_area,
    crop_title_strip,
    find_chat_hwnd,
    find_main_wechat_hwnd,
    screenshot_window,
)

logger = logging.getLogger("ocr-wechat-agent")

# 过滤时间标记行（如"10:30"、"昨天 20:05"、"2月28日"等）
_TIME_RE = re.compile(
    r"^(\d{1,2}:\d{2}(:\d{2})?|"           # 10:30 / 10:30:00
    r"(昨天|今天|星期[一二三四五六日])\s*\d{1,2}:\d{2}|"
    r"\d{1,2}月\d{1,2}日(\s*\d{1,2}:\d{2})?)$"
)


def _is_time_marker(text: str) -> bool:
    return bool(_TIME_RE.match(text.strip()))


# ──────────────────────────────────────────────
# 新消息差分：锚定算法
# ──────────────────────────────────────────────

def _find_anchor(anchor: list[str], curr_texts: list[str]) -> int:
    """在 curr_texts 中搜索 anchor 列表最后出现的位置。

    返回 anchor 末行在 curr_texts 中的下标，未找到返回 -1。
    """
    if not anchor or not curr_texts:
        return -1
    n = len(anchor)
    # 从后往前扫，找最后一次出现
    for i in range(len(curr_texts) - n, -1, -1):
        if curr_texts[i : i + n] == anchor:
            return i + n - 1
    # 宽松匹配：只匹配最后1行
    last = anchor[-1]
    for i in range(len(curr_texts) - 1, -1, -1):
        if curr_texts[i] == last:
            return i
    return -1


# ──────────────────────────────────────────────
# 消息组装
# ──────────────────────────────────────────────

@dataclass
class MessageGroup:
    """将连续 OcrLine 归属到同一消息气泡"""
    lines: list[OcrLine] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    @property
    def top(self) -> float:
        return self.lines[0].top if self.lines else 0.0


def _group_lines(lines: list[OcrLine], gap_ratio: float = 1.8) -> list[MessageGroup]:
    """按 Y 轴间距将 OcrLine 分组为消息气泡。

    相邻两行的间距若超过行高均值的 gap_ratio 倍，则认为是新的消息。
    """
    if not lines:
        return []
    groups: list[MessageGroup] = [MessageGroup([lines[0]])]
    avg_h = sum(l.height for l in lines) / len(lines) if lines else 16
    for ln in lines[1:]:
        prev = groups[-1].lines[-1]
        gap = ln.top - (prev.top + prev.height)
        if gap > avg_h * gap_ratio:
            groups.append(MessageGroup([ln]))
        else:
            groups[-1].lines.append(ln)
    return groups


def _build_payload(
    content: str,
    sender: str,
    transfer: ChatTransferConfig,
) -> dict:
    return {
        "id": f"msg_{uuid.uuid4().hex[:16]}",
        "type": "text",
        "attr": "other",   # OCR 无法区分 friend/self
        "content": content,
        "sender": sender,
        "sender_remark": "",
        "info": {
            "chat_type": "group",   # 默认 group，私聊场景 content 就是全部
            "chat_name": transfer.chat,
            "group_member_count": 0,
        },
    }


# ──────────────────────────────────────────────
# 每个会话的状态跟踪器
# ──────────────────────────────────────────────

@dataclass
class ChatTracker:
    transfer: ChatTransferConfig
    # 上一轮 OCR 文本行（strip后），用于差分
    prev_texts: list[str] = field(default_factory=list)
    # 是否是首次扫描（首次不上报，仅建立基线）
    first_scan: bool = True


# ──────────────────────────────────────────────
# asyncio 事件循环（守护线程）
# ──────────────────────────────────────────────

def _run_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _publish_sync(
    loop: asyncio.AbstractEventLoop,
    js: JetStreamContext,
    subject: str,
    payload: dict,
) -> None:
    async def _do() -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            ack = await js.publish(subject, data)
            logger.info(
                "已发布 → %s (stream=%s seq=%d) sender=%r content=%r",
                subject, ack.stream, ack.seq,
                payload["sender"], payload["content"][:40],
            )
        except Exception:
            logger.exception("发布失败: subject=%s", subject)

    future = asyncio.run_coroutine_threadsafe(_do(), loop)
    try:
        future.result(timeout=10)
    except Exception:
        logger.exception("NATS 发布超时")


# ──────────────────────────────────────────────
# 核心轮询逻辑
# ──────────────────────────────────────────────

def _detect_active_chat_in_main_window(img: Image.Image, sidebar_pct: float) -> str:
    """通过 OCR 识别主微信窗口当前激活的会话名。"""
    strip = crop_title_strip(img, sidebar_pct=sidebar_pct)
    lines = recognize(strip)
    return lines[0].text if lines else ""


def _poll_chat(
    tracker: ChatTracker,
    cfg: Config,
    loop: asyncio.AbstractEventLoop,
    js: JetStreamContext,
) -> None:
    chat = tracker.transfer.chat

    # ── 1. 优先找独立弹出窗口 ──────────────────────────────────────────
    hwnd = find_chat_hwnd(chat)
    left_pct = 0.0

    if not hwnd:
        # ── 2. 降级：尝试在主微信窗口中查找目标会话 ──────────────────
        main_hwnd = find_main_wechat_hwnd()
        if not main_hwnd:
            logger.debug("未找到会话窗口: %s，跳过本轮", chat)
            return

        # 主窗口最小化时无内容可 OCR，直接跳过
        import win32gui as _w32
        if _w32.IsIconic(main_hwnd):
            logger.debug("主窗口已最小化，无可见会话，跳过: %s", chat)
            return

        # 快速检测主窗口当前激活的是哪个会话
        main_img = screenshot_window(main_hwnd)
        if main_img is None:
            logger.debug("主窗口截图失败，跳过本轮")
            return

        active_chat = _detect_active_chat_in_main_window(main_img, cfg.sidebar_width_pct)
        # 宽松匹配：目标名是识别结果的子串，或识别结果是目标名的子串
        if chat not in active_chat and active_chat not in chat:
            logger.debug(
                "主窗口当前会话 %r ≠ 目标 %r，跳过本轮",
                active_chat, chat,
            )
            return

        logger.debug("主窗口 fallback: 识别到 %r，匹配目标 %r", active_chat, chat)
        hwnd = main_hwnd
        left_pct = cfg.sidebar_width_pct
        img = main_img
    else:
        img = screenshot_window(hwnd)

    if img is None:
        logger.debug("截图失败: %s", chat)
        return

    cropped = crop_message_area(img, top_pct=cfg.message_area_top_pct, left_pct=left_pct)
    ocr_lines = recognize(cropped)

    if not ocr_lines:
        return

    # 过滤时间标记
    ocr_lines = [l for l in ocr_lines if not _is_time_marker(l.text)]
    curr_texts = [l.text for l in ocr_lines]

    if tracker.first_scan:
        # 首次扫描：建立基线，不上报任何消息
        tracker.prev_texts = curr_texts[-max(cfg.anchor_lines * 3, 15):]
        tracker.first_scan = False
        logger.info("已建立基线: %s，共 %d 行", chat, len(tracker.prev_texts))
        return

    # 差分：找到锚在新结果中的位置
    anchor = tracker.prev_texts[-cfg.anchor_lines:]
    anchor_pos = _find_anchor(anchor, curr_texts)

    if anchor_pos >= 0:
        new_texts = curr_texts[anchor_pos + 1:]
        new_lines = ocr_lines[anchor_pos + 1:]
    else:
        # 锚丢失（可能滚动太多）：只取底部半屏新内容
        half = len(curr_texts) // 2
        new_texts = curr_texts[half:]
        new_lines = ocr_lines[half:]
        logger.debug("锚定失败(%s)，取底部 %d 行", chat, len(new_texts))

    # 截断，防止首次建立基线失效时爆发大量消息
    if len(new_texts) > cfg.max_new_lines_per_poll:
        new_texts = new_texts[-cfg.max_new_lines_per_poll:]
        new_lines = new_lines[-cfg.max_new_lines_per_poll:]

    if not new_lines:
        # 更新 prev_texts（避免窗口内容滚动后锚永远匹配旧位置）
        tracker.prev_texts = curr_texts[-max(cfg.anchor_lines * 3, 15):]
        return

    # 将新行按气泡分组，每组发一条消息
    groups = _group_lines(new_lines)
    for group in groups:
        lines_in_group = group.lines
        if not lines_in_group:
            continue

        # 尝试从第一行推断 sender（短行 ≤ 12 字符，且后面还有内容）
        if len(lines_in_group) >= 2 and len(lines_in_group[0].text) <= 12:
            sender = lines_in_group[0].text
            content = "\n".join(l.text for l in lines_in_group[1:])
        else:
            sender = chat
            content = "\n".join(l.text for l in lines_in_group)

        if not content.strip():
            continue

        payload = _build_payload(content, sender, tracker.transfer)
        _publish_sync(loop, js, tracker.transfer.subject, payload)

    # 更新基线
    tracker.prev_texts = curr_texts[-max(cfg.anchor_lines * 3, 15):]


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

def main() -> None:
    # COM STA 初始化（WinRT OCR 和 win32 API 都需要）
    pythoncom.CoInitialize()

    cfg = load_config_from_args()
    init_logger(cfg.logger)
    logger.info("ocr-wechat-agent 启动，监听 %d 个会话", len(cfg.chat_transfer_config))

    if not cfg.chat_transfer_config:
        logger.warning("chat_transfer_config 为空，退出")
        return

    # 启动 asyncio 守护线程
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=_run_event_loop, args=(loop,), daemon=True)
    t.start()

    # 连接 NATS
    logger.info("正在连接 NATS: %s", cfg.nats_url)
    nc = asyncio.run_coroutine_threadsafe(nats.connect(cfg.nats_url), loop).result(timeout=10)
    js = nc.jetstream()
    logger.info("NATS JetStream 连接成功")

    # 初始化每个会话的跟踪器
    trackers = [ChatTracker(transfer=t) for t in cfg.chat_transfer_config]

    logger.info("开始轮询（间隔 %.1f 秒）", cfg.poll_interval)
    try:
        while True:
            for tracker in trackers:
                try:
                    _poll_chat(tracker, cfg, loop, js)
                except Exception:
                    logger.exception("轮询异常: %s", tracker.transfer.chat)
            time.sleep(cfg.poll_interval)
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    finally:
        asyncio.run_coroutine_threadsafe(nc.drain(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=5)
        pythoncom.CoUninitialize()
        logger.info("已退出")


if __name__ == "__main__":
    main()

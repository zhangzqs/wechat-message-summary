"""Windows 原生 OCR 引擎封装（基于 WinRT Windows.Media.Ocr）

不依赖外部 OCR 工具，调用 Windows 10/11 内置 OCR。
识别语言取决于系统已安装的语言包，通常包含简体中文。

用法：
    from ocr_engine import recognize
    lines = recognize(pil_image)   # 返回 list[OcrLine]
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger("ocr-wechat-agent")


@dataclass
class OcrLine:
    """单行 OCR 结果，包含文字和在原图中的纵坐标（用于排序/分组）"""

    text: str
    top: float   # 行顶部 y 坐标（像素）
    left: float  # 行左侧 x 坐标
    width: float
    height: float

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2


async def _recognize_async(pil_image: Image.Image) -> list[OcrLine]:
    """WinRT OcrEngine 异步识别，返回带坐标的文本行列表。"""
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter

    buf = io.BytesIO()
    # WinRT OCR 对 >= 40 像素高度的字符识别效果最好
    pil_image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png_bytes)
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    # 优先使用用户语言包（含已安装的中文识别）
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        # 降级到英文
        from winsdk.windows.globalization import Language
        engine = OcrEngine.try_create_from_language(Language("en-US"))
    if engine is None:
        logger.warning("WinRT OCR: 无法创建识别引擎")
        return []

    result = await engine.recognize_async(bitmap)

    lines: list[OcrLine] = []
    for line in result.lines:
        words = list(line.words)
        if not words:
            continue

        # 根据 bounding box 间距智能拼接：间距 < 平均字符宽 × 阈值 → 直接拼接（无空格），
        # 否则插入空格。此策略同时处理 CJK 字符间和 OCR 错误断词（如 sunnysab→su nnysa b）。
        parts: list[str] = []
        for i, w in enumerate(words):
            parts.append(w.text)
            if i < len(words) - 1:
                gap = words[i + 1].bounding_rect.x - (w.bounding_rect.x + w.bounding_rect.width)
                # 用较短单词的平均字符宽作为基准
                avg_cw = min(
                    w.bounding_rect.width / max(len(w.text), 1),
                    words[i + 1].bounding_rect.width / max(len(words[i + 1].text), 1),
                )
                if gap >= avg_cw * 0.9:
                    parts.append(" ")

        text = _clean_text("".join(parts).strip())
        if not text:
            continue

        lefts  = [w.bounding_rect.x for w in words]
        tops   = [w.bounding_rect.y for w in words]
        rights = [w.bounding_rect.x + w.bounding_rect.width for w in words]
        bots   = [w.bounding_rect.y + w.bounding_rect.height for w in words]
        lines.append(OcrLine(
            text=text,
            left=min(lefts),
            top=min(tops),
            width=max(rights) - min(lefts),
            height=max(bots) - min(tops),
        ))

    # 按自上而下排序
    lines.sort(key=lambda l: l.top)
    return lines


_CJK_SPACE_RE = re.compile(r"(?<=[\u4e00-\u9fff\uff00-\uffef\u3000-\u303f])"
                            r" "
                            r"(?=[\u4e00-\u9fff\uff00-\uffef\u3000-\u303f\u0021-\u007e])"
                            "|"
                            r"(?<=[\u0021-\u007e])"
                            r" "
                            r"(?=[\u4e00-\u9fff\uff00-\uffef\u3000-\u303f])")


def _clean_text(text: str) -> str:
    """去除 WinRT OCR 在中文字符间插入的多余空格。"""
    # 多次迭代直到稳定（字符间可多个空格）
    prev = None
    while prev != text:
        prev = text
        text = _CJK_SPACE_RE.sub("", text)
    return text.strip()


def recognize(pil_image: Image.Image) -> list[OcrLine]:
    """同步接口：对 PIL 图像执行 Windows WinRT OCR，返回排序后的文本行列表。

    注意：此函数必须在主线程调用（已 pythoncom.CoInitialize 的 STA 线程）。
    内部用 asyncio.run() 启动一个新事件循环来执行 WinRT 异步 API。
    """
    try:
        return asyncio.run(_recognize_async(pil_image))
    except Exception:
        logger.exception("OCR 识别异常")
        return []

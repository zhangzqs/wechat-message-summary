"""微信窗口管理模块

职责：
1. 按窗口标题找到微信独立聊天窗口 HWND（微信 4.x 每个独立对话是一个顶级 Qt 窗口）
2. 用 PrintWindow(PW_RENDERFULLCONTENT) 截图（不需要窗口可见/置顶）
3. 裁剪掉顶部导航栏区域，只保留消息列表区域
"""
from __future__ import annotations

import ctypes
import logging

import win32con
import win32gui
import win32process
import win32ui
import psutil
from PIL import Image

logger = logging.getLogger("ocr-wechat-agent")

# PW_RENDERFULLCONTENT：让 PrintWindow 渲染完整图层（支持 DirectComposition/Qt）
_PW_RENDERFULLCONTENT = 0x00000002

# WeChat 主进程名
_WEIXIN_PROC = "Weixin.exe"


def _get_weixin_pids() -> set[int]:
    """返回当前所有 Weixin.exe 进程的 PID 集合。"""
    return {
        p.pid
        for p in psutil.process_iter(["name"])
        if p.info.get("name") == _WEIXIN_PROC
    }


def find_main_wechat_hwnd() -> int:
    """查找主微信窗口（标题 = '微信'）的 HWND，用于独立聊天窗口消失时的 fallback。"""
    wx_pids = _get_weixin_pids()
    if not wx_pids:
        return 0

    result: list[int] = []

    def _cb(hwnd: int, _: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        if pid not in wx_pids:
            return True
        if win32gui.GetWindowText(hwnd) == "微信":
            result.append(hwnd)
        return True

    win32gui.EnumWindows(_cb, None)
    if result:
        logger.debug("find_main_wechat_hwnd: hwnd=%d", result[0])
    return result[0] if result else 0


def find_chat_hwnd(chat_name: str) -> int:
    """在所有顶级窗口中寻找标题与 chat_name 完全匹配的微信窗口句柄。

    微信 4.x 的独立聊天窗口标题 = 会话名称（群名/好友名）。
    返回 0 表示未找到。
    """
    wx_pids = _get_weixin_pids()
    if not wx_pids:
        logger.debug("find_chat_hwnd: 未找到 Weixin.exe 进程")
        return 0

    result: list[int] = []

    def _cb(hwnd: int, _: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        if pid not in wx_pids:
            return True
        title = win32gui.GetWindowText(hwnd)
        if title == chat_name:
            result.append(hwnd)
        return True

    win32gui.EnumWindows(_cb, None)
    if result:
        logger.debug("find_chat_hwnd: chat=%r hwnd=%d", chat_name, result[0])
        return result[0]
    return 0


def screenshot_window(hwnd: int) -> Image.Image | None:
    """用 PrintWindow 截取指定 HWND 的完整内容（兼容 Qt/DComp 合成窗口）。

    返回 PIL.Image（RGB），失败返回 None。
    """
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w = right - left
        h = bottom - top
        if w <= 0 or h <= 0:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)

        # PW_RENDERFULLCONTENT 确保 Qt 渲染完整内容
        ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), _PW_RENDERFULLCONTENT)
        if not ok:
            logger.debug("PrintWindow 返回 0（hwnd=%d），尝试普通截图", hwnd)
            # 降级：用 BitBlt 从屏幕 DC 复制（需窗口可见）
            screen_dc = win32gui.GetDC(0)
            screen_mfc = win32ui.CreateDCFromHandle(screen_dc)
            save_dc.BitBlt((0, 0), (w, h), screen_mfc, (left, top), win32con.SRCCOPY)
            win32gui.ReleaseDC(0, screen_dc)
            screen_mfc.DeleteDC()

        bmp_info = bmp.GetInfo()
        bmp_bits = bmp.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_bits,
            "raw",
            "BGRX",
            0,
            1,
        )

        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return img
    except Exception:
        logger.exception("screenshot_window 失败（hwnd=%d）", hwnd)
        return None


def crop_message_area(
    img: Image.Image,
    top_pct: float = 0.12,
    left_pct: float = 0.0,
) -> Image.Image:
    """裁剪掉顶部导航栏/标题栏（以及可选的左侧边栏），返回消息列表区域。

    Args:
        img: 完整窗口截图
        top_pct: 裁掉顶部的比例（0.12 = 12%，覆盖标题栏+搜索栏）
        left_pct: 裁掉左侧边栏的比例（主窗口 fallback 时传入 sidebar_width_pct）
    """
    w, h = img.size
    top_px = int(h * top_pct)
    left_px = int(w * left_pct)
    return img.crop((left_px, top_px, w, h))


def crop_title_strip(
    img: Image.Image,
    sidebar_pct: float = 0.27,
    title_top_pct: float = 0.03,
    title_bottom_pct: float = 0.10,
) -> Image.Image:
    """从主微信窗口截图中裁出右侧面板的会话标题条，用于识别当前激活的会话。

    Args:
        img: 主微信窗口完整截图
        sidebar_pct: 左侧边栏占总宽度的比例
        title_top_pct / title_bottom_pct: 标题条距窗口顶部的高度区间
    """
    w, h = img.size
    return img.crop((
        int(w * sidebar_pct),
        int(h * title_top_pct),
        w,
        int(h * title_bottom_pct),
    ))

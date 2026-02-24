"""消息分类与 payload 构建模块

根据 pyweixin UI 元素的 class_name 和 window_text 判断消息类型，
构建与 Go 端 ReceivedMessage 契约一致的 JSON payload。

pyweixin 消息类型识别（UI class_name）：
- mmui::ChatTextItemView          → 文本消息
- mmui::ChatBubbleItemView        → 链接/文件/红包/其他（根据文本前缀判断）
- mmui::ChatBubbleReferItemView   → 图片/视频/其他（根据文本内容判断）
"""

import uuid


def classify_message(class_name: str, text: str) -> tuple[str, str]:
    """根据 UI 元素 class_name 和文本内容判断消息类型和属性。

    返回:
        (message_type, message_attr) 元组，与 Go 端 enums 对齐。
    """
    if class_name == "mmui::ChatTextItemView":
        return ("text", "friend")

    if class_name == "mmui::ChatBubbleItemView":
        if text.startswith("[链接]"):
            return ("link", "friend")
        if "文件" in text:
            return ("file", "friend")
        if "微信红包" in text:
            return ("other", "friend")
        return ("other", "friend")

    if class_name == "mmui::ChatBubbleReferItemView":
        if "图片" in text:
            return ("image", "friend")
        if "视频" in text:
            return ("video", "friend")
        return ("quote", "friend")

    return ("other", "other")


def parse_sender_and_content(text: str, chat_name: str) -> tuple[str, str]:
    """从 window_text 中尝试解析 sender 和 content。

    微信群聊文本消息的 window_text() 格式通常为 "发送者名\\n消息内容"。
    私聊或无法解析时，sender 降级为 chat_name。

    返回:
        (sender, content) 元组。
    """
    if "\n" in text:
        first_newline = text.index("\n")
        sender = text[:first_newline].strip()
        content = text[first_newline + 1:].strip()
        if sender:
            return (sender, content)

    return (chat_name, text.strip())


def build_payload(
    *,
    text: str,
    class_name: str,
    chat_name: str,
) -> dict:
    """将 UI 元素信息构建为与 Go 端 ReceivedMessage 契约一致的 dict。

    参数:
        text: UI 元素的 window_text() 返回值
        class_name: UI 元素的 class_name() 返回值
        chat_name: 会话名称（来自配置 chat_transfer_config.chat）

    返回:
        符合消息契约的 dict，可直接 json.dumps 后发布到 NATS。
    """
    msg_type, msg_attr = classify_message(class_name, text)
    sender, content = parse_sender_and_content(text, chat_name)

    return {
        "id": f"msg_{uuid.uuid4().hex[:16]}",
        "type": msg_type,
        "attr": msg_attr,
        "content": content,
        "sender": sender,
        "sender_remark": "",
        "chat_type": "group",
        "chat_name": chat_name,
    }

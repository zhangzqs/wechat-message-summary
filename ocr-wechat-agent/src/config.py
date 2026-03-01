"""配置加载模块：argparse + YAML + Pydantic 验证"""

import argparse
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class LoggerConfig(BaseModel):
    """日志配置"""

    level: str = Field(default="INFO")
    filename: str = Field(default="ocr-wechat-agent.log")
    max_bytes: int = Field(default=10 * 1024 * 1024)
    backup_count: int = Field(default=7)


class ChatTransferConfig(BaseModel):
    """单条微信会话 → NATS 主题映射"""

    chat: str = Field(description="微信会话名称（好友备注/群名），需与窗口标题完全一致")
    subject: str = Field(default="wxauto.messages")


class Config(BaseModel):
    """应用顶层配置"""

    logger: LoggerConfig = Field(default_factory=LoggerConfig)
    nats_url: str = Field(default="nats://localhost:4222")
    poll_interval: float = Field(default=1.5, description="轮询间隔秒数")
    message_area_top_pct: float = Field(default=0.12, description="裁剪掉顶部导航栏的比例")
    sidebar_width_pct: float = Field(default=0.27, description="主窗口左侧边栏占总宽度的比例（fallback 模式使用）")
    anchor_lines: int = Field(default=4, description="用于检测新消息的锚定行数")
    max_new_lines_per_poll: int = Field(default=20, description="每轮最多上报行数")
    chat_transfer_config: list[ChatTransferConfig] = Field(default_factory=list)


def load_config_from_args() -> Config:
    parser = argparse.ArgumentParser(description="ocr-wechat-agent")
    parser.add_argument("--config", type=str, default="config.yaml")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return Config.model_validate(raw)

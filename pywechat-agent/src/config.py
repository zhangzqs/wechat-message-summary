"""配置加载模块：argparse + YAML + Pydantic 验证"""

import argparse
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class LoggerConfig(BaseModel):
    """日志配置"""

    level: str = Field(default="INFO", description="日志级别")
    filename: str = Field(default="pywechat-agent.log", description="日志文件名")
    max_bytes: int = Field(default=10 * 1024 * 1024, description="单个日志文件最大字节数")
    backup_count: int = Field(default=7, description="日志文件保留数量")


class ChatTransferConfig(BaseModel):
    """单条微信会话 → NATS 主题映射"""

    chat: str = Field(description="微信会话名称（好友备注/群名）")
    subject: str = Field(default="wxauto.messages", description="NATS JetStream 主题")


class Config(BaseModel):
    """应用顶层配置"""

    logger: LoggerConfig = Field(default_factory=LoggerConfig)
    nats_url: str = Field(default="nats://localhost:4222", description="NATS 服务器地址")
    poll_interval: float = Field(default=0.5, description="轮询间隔秒数")
    window_minimize: bool = Field(default=True, description="监听窗口是否最小化")
    chat_transfer_config: list[ChatTransferConfig] = Field(
        default_factory=list,
        description="会话转发配置列表",
    )


def load_config_from_args() -> Config:
    """从命令行参数解析配置文件路径，加载 YAML 并返回 Pydantic 校验后的 Config。"""
    parser = argparse.ArgumentParser(
        description="pywechat-agent: pyweixin → NATS publisher"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="配置文件路径（默认: config.yaml）",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return Config.model_validate(raw)

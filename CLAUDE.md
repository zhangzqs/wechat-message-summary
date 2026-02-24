# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

微信群消息每日总结系统。采集微信聊天消息 → NATS JetStream 中转 → 持久化到数据库 → MCP Server 对外暴露查询接口。

```
WeChat Desktop ──wxauto──▶ wechat-agent (Python) ──JSON──▶ NATS JetStream
                                                                │
backend-go: wxautoconsumer ◀──Pull Subscribe──────────────────────┘
      │
      ├──▶ SQLite / PostgreSQL (GORM)
      │
      └──▶ MCP Server (HTTP SSE, :8080) ──▶ Claude / AI Agents
```

## Build & Run

### backend-go

```bash
cd backend-go
go build -o wechat-backend ./cmd          # 构建
go run ./cmd --config cmd/config.yaml     # 直接运行
go test ./pkg/natconsumer/... -v          # 运行 NATS 消费者集成测试（需要 NATS 服务）
```

Go 版本：1.25.5。无 Makefile，无 Docker。

### wechat-agent

```bash
cd wechat-agent
uv sync                                          # 安装依赖
uv run wechat-agent --config config.yaml          # 运行（仅 Windows，需微信桌面端运行中）
```

Python 版本：3.13+，包管理器 uv。PyPI 镜像：清华源。

## Architecture

### 双服务架构，NATS 解耦

- **wechat-agent**（Python）：wxauto 监听微信 → 同步回调通过 `asyncio.run_coroutine_threadsafe` 桥接到独立线程的 asyncio 事件循环 → NATS JetStream publish
- **backend-go**：NATS Pull Subscribe 消费消息 → GORM 持久化 → MCP Server 暴露 `list_messages` 工具

### backend-go 核心模式

**Runner 框架**（`pkg/runner/`）：所有服务实现 `Runner` 接口（`Name()` + `Run(ctx)`），由 `runner.Run()` 并发启动，统一信号处理优雅关闭。当前有两个 runner：`wxautoconsumer` 和 `mcpserver`。

**NATS 消费者**（`pkg/natconsumer/`）：通用 JetStream Pull 消费者，可配置并发 worker 数。消息处理回调返回 `ACK`/`NAK`/`TERM` 控制确认行为。

**数据库层**（`internal/common/databases/`）：GORM 实体 + CRUD，支持 SQLite/PostgreSQL 切换。分页采用 `created_at` 游标。

### wechat-agent 线程模型

wxauto 的 `KeepRunning()` 阻塞主线程做 UI 轮询，asyncio 事件循环在守护线程中 `run_forever()`。回调通过 `run_coroutine_threadsafe` 跨线程提交 NATS 发布协程。

## Message Contract

Python 端构造、Go 端消费的统一 JSON 格式：

```json
{
  "id": "msg_<16-char-hex>",
  "type": "text|image|voice|video|file|quote|location|link|emotion|merge|personal_card|note|other",
  "attr": "friend|self|system|tickle|time|other",
  "content": "...",
  "sender": "...",
  "sender_remark": "...",
  "info": {
    "chat_type": "friend|group|service|official",
    "chat_name": "会话名称",
    "group_member_count": 100
  }
}
```

枚举定义在 `backend-go/internal/common/enums/messasge_attr.go`（注意文件名拼写）。Python 端映射在 `wechat-agent/src/main.py` 的 `_MSG_ATTR_MAP`。

## Config

两端均使用 YAML 配置 + `--config` CLI 参数：
- Go 端：`backend-go/cmd/config.yaml`（logger / database / wxautoconsumer / mcpserver）
- Python 端：`wechat-agent/config.yaml`（logger / nats_url / chat_transfer_config）

NATS 默认地址 `nats://localhost:4222`，默认 subject `wxauto.messages`。

## Code Conventions

- Go 注释和日志使用中文
- Python docstring 和注释使用中文
- 结构化日志：Go 用 zerolog（JSON + console），Python 用 python-json-logger（JSON file）+ StreamHandler（console）

# wechat-message-summary

每日总结微信群消息

## 初始化 NATS JetStream

项目使用 NATS JetStream 作为消息中间件。Go 消费端只执行 `PullSubscribe`，不会自动创建 Stream，因此需要手动初始化。

### 1. 安装并启动 NATS Server（启用 JetStream）

```bash
# Docker 方式（推荐）
docker run -d --name nats -p 4222:4222 nats:latest -js

# 或直接安装运行
# https://docs.nats.io/running-a-nats-service/introduction/installation
nats-server -js
```

### 2. 安装 NATS CLI

```bash
# macOS
brew install nats-io/nats-tools/nats

# Go install
go install github.com/nats-io/natscli/nats@latest

# 其他方式见 https://github.com/nats-io/natscli
```

### 3. 创建 Stream

```bash
nats stream add wxauto \
  --subjects "wxauto.messages" \
  --retention limits \
  --max-msgs -1 \
  --max-bytes -1 \
  --max-age 30d \
  --storage file \
  --replicas 1 \
  --discard old \
  --max-msg-size -1 \
  --dupe-window 2m
```

参数说明：
- `--subjects "wxauto.messages"`：Stream 监听的 subject，与两端配置一致
- `--retention limits`：达到上限时按策略丢弃旧消息
- `--max-age 30d`：消息保留 30 天
- `--storage file`：持久化到磁盘
- `--dupe-window 2m`：去重窗口 2 分钟

### 4. 验证

```bash
# 查看 Stream 状态
nats stream info wxauto

# 订阅消息（调试用）
nats sub wxauto.messages

# 手动发布测试消息
nats pub wxauto.messages '{"id":"test_001","type":"text","attr":"friend","content":"hello","sender":"test","sender_remark":"","info":{"chat_type":"friend","chat_name":"测试会话"}}'
```

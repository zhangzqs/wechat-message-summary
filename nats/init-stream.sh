#!/bin/sh
# 等待 NATS Server 就绪
echo "[init] 等待 NATS Server 启动..."
until nats server check connection --server="$NATS_URL" >/dev/null 2>&1; do
  sleep 1
done
echo "[init] NATS Server 已就绪"

# 创建 Stream: wxauto
echo "[init] 创建 JetStream Stream: wxauto (subjects: wxauto.messages)"
nats stream add wxauto \
  --server="$NATS_URL" \
  --subjects="wxauto.messages" \
  --retention=limits \
  --max-msgs=-1 \
  --max-bytes=-1 \
  --max-age=30d \
  --storage=file \
  --replicas=1 \
  --discard=old \
  --max-msg-size=-1 \
  --dupe-window=2m \
  --defaults \
  2>/dev/null

# 若已存在则忽略错误
echo "[init] Stream 初始化完毕"
nats stream info wxauto --server="$NATS_URL"

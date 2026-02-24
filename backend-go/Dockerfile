# ---- 构建阶段 ----
FROM golang:1.25-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 go build -o /bin/wechat-backend ./cmd

# ---- 运行阶段 ----
FROM alpine:3.21

RUN apk add --no-cache ca-certificates tzdata
ENV TZ=Asia/Shanghai

COPY --from=builder /bin/wechat-backend /usr/local/bin/wechat-backend

WORKDIR /app
ENTRYPOINT ["wechat-backend"]
CMD ["--config", "/app/config.yaml"]

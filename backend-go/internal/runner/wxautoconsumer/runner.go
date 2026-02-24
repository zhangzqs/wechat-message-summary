package wxautoconsumer

import (
	"context"
	"encoding/json"

	"github.com/nats-io/nats.go"
	"github.com/rs/zerolog"

	db "github.com/zhangzqs/wechat-message-summary/backend-go/internal/common/databases"
	wxauto "github.com/zhangzqs/wechat-message-summary/backend-go/internal/common/messages"
	natsconsumer "github.com/zhangzqs/wechat-message-summary/backend-go/pkg/natconsumer"
)

// Config 是 WxAutoConsumer 的配置
type Config struct {
	Consumer natsconsumer.Config `yaml:"consumer"` // NATS 消费者配置
}

// Runner 负责订阅 NATS 消息并持久化到数据库
type Runner struct {
	cfg          *Config
	messageTable *db.MessageTable
}

// New 创建一个新的 WxAutoConsumer Runner
func New(cfg *Config, messageTable *db.MessageTable) *Runner {
	return &Runner{
		cfg:          cfg,
		messageTable: messageTable,
	}
}

func (r *Runner) Name() string {
	return "wxautoconsumer"
}

// Run 启动消费者，阻塞直到 ctx 取消
func (r *Runner) Run(ctx context.Context) error {
	consumer := natsconsumer.New(&r.cfg.Consumer)
	return consumer.Run(ctx, r.handleMessage)
}

// handleMessage 处理单条 NATS 消息：反序列化 → 转换 → 持久化
func (r *Runner) handleMessage(ctx context.Context, msg *nats.Msg) natsconsumer.HandleResult {
	logger := zerolog.Ctx(ctx)

	// 反序列化消息
	var received wxauto.ReceivedMessage
	if err := json.Unmarshal(msg.Data, &received); err != nil {
		logger.Error().Err(err).Msg("反序列化消息失败，丢弃该消息")
		return natsconsumer.HandleResultTerm
	}

	// 转换为数据库实体
	entity := convertToEntity(&received)

	// 持久化
	if err := r.messageTable.Create(ctx, entity); err != nil {
		logger.Error().Err(err).Str("message_id", entity.ID).Msg("持久化消息失败，消息将重新入队")
		return natsconsumer.HandleResultNak
	}

	logger.Debug().Str("message_id", entity.ID).Msg("消息已持久化")
	return natsconsumer.HandleResultAck
}

// convertToEntity 将 ReceivedMessage 转换为 MessageEntity
func convertToEntity(msg *wxauto.ReceivedMessage) *db.MessageEntity {
	return &db.MessageEntity{
		ID:           msg.ID,
		Type:         msg.Type,
		Attr:         msg.Attr,
		Content:      msg.Content,
		Sender:       msg.Sender,
		SenderRemark: msg.SenderRemark,
		ChatType:     msg.ChatType,
		ChatName:     msg.ChatName,
	}
}

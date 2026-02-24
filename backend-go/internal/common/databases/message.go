package db

import (
	"context"
	"time"

	"github.com/zhangzqs/wechat-message-summary/backend-go/internal/common/enums"
	"gorm.io/gorm"
)

type MessageEntity struct {
	ID               string            `gorm:"primaryKey"`                // 消息唯一 ID
	Type             enums.MessageType `gorm:"type"`                      // 消息类型（内容属性）
	Attr             enums.MessageAttr `gorm:"attr"`                      // 消息属性（来源属性）
	Content          string            `gorm:"content"`                   // 消息内容
	Sender           string            `gorm:"sender"`                    // 发送者
	SenderRemark     string            `gorm:"sender_remark"`             // 发送者备注
	ChatType         string            `gorm:"chat_type"`                 // 会话类型
	ChatName         string            `gorm:"chat_name"`                 // 会话名称
	GroupMemberCount *int              `gorm:"group_member_count"`        // 此时的群成员数量，只有在群聊会话时才有
	CreatedAt        time.Time         `gorm:"created_at;autoCreateTime"` // 消息创建时间
	UpdatedAt        time.Time         `gorm:"updated_at;autoUpdateTime"` // 消息更新时间
}

type MessageTable struct {
	db *gorm.DB
}

func NewMessageTable(db *gorm.DB) *MessageTable {
	return &MessageTable{db: db}
}

func (t *MessageTable) Create(ctx context.Context, message *MessageEntity) error {
	return gorm.G[MessageEntity](t.db).Create(ctx, message)
}

type MessageTableListOptions struct {
	MessageType  *string    // 消息类型
	Sender       *string    // 发送者
	CreatedAtGTE *time.Time // 创建时间大于等于
	CreatedAtLTE *time.Time // 创建时间小于等于
	Limit        int        // 返回的消息数量限制，默认为 100 条
}

func (t *MessageTable) List(ctx context.Context, marker string, options *MessageTableListOptions) (ret []MessageEntity, nextMarker string, err error) {
	query := gorm.G[MessageEntity](t.db).Order("created_at desc").Limit(options.Limit + 1) // 多取一条记录用于判断是否有下一页

	if options.MessageType != nil {
		query = query.Where("type = ?", *options.MessageType)
	}
	if options.Sender != nil {
		query = query.Where("sender = ?", *options.Sender)
	}
	if options.CreatedAtGTE != nil {
		query = query.Where("created_at >= ?", *options.CreatedAtGTE)
	}
	if options.CreatedAtLTE != nil {
		query = query.Where("created_at <= ?", *options.CreatedAtLTE)
	}
	if marker != "" {
		query = query.Where("created_at < ?", marker) // 使用 created_at 作为分页标记
	}

	messages, err := query.Find(ctx)
	if err != nil {
		return nil, "", err
	}

	if len(messages) > options.Limit {
		ret = messages[:options.Limit]
		nextMarker = ret[len(ret)-1].CreatedAt.Format(time.RFC3339Nano) // 使用最后一条记录的 created_at 作为下一页的标记
	} else {
		ret = messages
		nextMarker = ""
	}

	return ret, nextMarker, nil
}

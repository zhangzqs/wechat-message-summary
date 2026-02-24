package wxauto

import "github.com/zhangzqs/wechat-message-summary/backend-go/internal/common/enums"

type ReceivedMessage struct {
	ID           string            `json:"id"`            // 消息唯一 ID
	Type         enums.MessageType `json:"type"`          // 消息类型（内容属性），如 text/image/voice 等
	Attr         enums.MessageAttr `json:"attr"`          // 消息属性（来源属性），如 self/friend/system 等
	Content      string            `json:"content"`       // 消息内容
	Sender       string            `json:"sender"`        // 发送者
	SenderRemark string            `json:"sender_remark"` // 发送者备注
	ChatType     string            `json:"chat_type"`     // 会话类型
	ChatName     string            `json:"chat_name"`     // 会话名称
}

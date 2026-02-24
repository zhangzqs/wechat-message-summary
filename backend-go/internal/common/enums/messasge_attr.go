package enums

// 消息属性（来源属性）
type MessageAttr string

const (
	MessageAttrSystem MessageAttr = "system" // 系统消息
	MessageAttrTime   MessageAttr = "time"   // 时间消息
	MessageAttrTickle MessageAttr = "tickle" // 拍一拍消息
	MessageAttrSelf   MessageAttr = "self"   // 自己发送的消息
	MessageAttrFriend MessageAttr = "friend" // 好友消息
	MessageAttrOther  MessageAttr = "other"  // 其他消息
)

// 消息类型（内容属性）
type MessageType string

const (
	MessageTypeText         MessageType = "text"          // 文本消息
	MessageTypeQuote        MessageType = "quote"         // 引用消息
	MessageTypeVoice        MessageType = "voice"         // 语音消息
	MessageTypeImage        MessageType = "image"         // 图片消息
	MessageTypeVideo        MessageType = "video"         // 视频消息
	MessageTypeFile         MessageType = "file"          // 文件消息
	MessageTypeLocation     MessageType = "location"      // 位置消息
	MessageTypeLink         MessageType = "link"          // 链接消息
	MessageTypeEmotion      MessageType = "emotion"       // 表情消息
	MessageTypeMerge        MessageType = "merge"         // 合并转发消息
	MessageTypePersonalCard MessageType = "personal_card" // 个人名片消息
	MessageTypeNote         MessageType = "note"          // 笔记消息
	MessageTypeOther        MessageType = "other"         // 其他消息
)

// 会话类型
type ChatType string

const (
	ChatTypeFriend   ChatType = "friend"   // 好友会话
	ChatTypeGroup    ChatType = "group"    // 群聊会话
	ChatTypeSystem   ChatType = "service"  // 客服会话
	ChatTypeOfficial ChatType = "official" // 公众号会话
)

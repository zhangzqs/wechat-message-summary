package mcpserver

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/rs/zerolog"

	db "github.com/zhangzqs/wechat-message-summary/backend-go/internal/common/databases"
)

// Config 是 MCP Server 的配置
type Config struct {
	Addr string `yaml:"addr"` // HTTP 监听地址，如 ":8080"
}

// Runner 负责启动 MCP Server 并提供消息查询工具
type Runner struct {
	cfg          *Config
	messageTable *db.MessageTable
}

// New 创建一个新的 MCP Server Runner
func New(cfg *Config, messageTable *db.MessageTable) *Runner {
	return &Runner{
		cfg:          cfg,
		messageTable: messageTable,
	}
}

func (r *Runner) Name() string {
	return "mcpserver"
}

// listMessagesInput 定义 list_messages 工具的输入参数
type listMessagesInput struct {
	MessageType  *string `json:"message_type,omitempty" jsonschema:"description=消息类型过滤，如 text/image/voice 等"`
	Sender       *string `json:"sender,omitempty" jsonschema:"description=发送者过滤"`
	CreatedAtGTE *string `json:"created_at_gte,omitempty" jsonschema:"description=起始时间过滤（RFC3339 格式）"`
	CreatedAtLTE *string `json:"created_at_lte,omitempty" jsonschema:"description=结束时间过滤（RFC3339 格式）"`
	Limit        int     `json:"limit,omitempty" jsonschema:"description=返回数量限制，默认 100"`
	Marker       string  `json:"marker,omitempty" jsonschema:"description=分页游标，传入上一次返回的 next_marker 获取下一页"`
}

// listMessagesOutput 定义 list_messages 工具的输出
type listMessagesOutput struct {
	Messages   []messageItem `json:"messages"`
	NextMarker string        `json:"next_marker,omitempty"`
}

// messageItem 是返回给 MCP 客户端的消息条目
type messageItem struct {
	ID               string `json:"id"`
	Type             string `json:"type"`
	Attr             string `json:"attr"`
	Content          string `json:"content"`
	Sender           string `json:"sender"`
	SenderRemark     string `json:"sender_remark"`
	ChatType         string `json:"chat_type"`
	ChatName         string `json:"chat_name"`
	GroupMemberCount *int   `json:"group_member_count,omitempty"`
	CreatedAt        string `json:"created_at"`
}

// Run 启动 MCP Server，阻塞直到 ctx 取消
func (r *Runner) Run(ctx context.Context) error {
	logger := zerolog.Ctx(ctx)

	server := mcp.NewServer(
		&mcp.Implementation{
			Name:    "wechat-message-summary",
			Version: "v1.0.0",
		},
		nil,
	)

	// 注册 list_messages 工具
	mcp.AddTool(server, &mcp.Tool{
		Name:        "list_messages",
		Description: "查询微信消息列表，支持按类型、发送者、时间范围过滤，支持分页",
	}, r.handleListMessages)

	handler := mcp.NewStreamableHTTPHandler(func(_ *http.Request) *mcp.Server {
		return server
	}, nil)

	httpServer := &http.Server{
		Addr:    r.cfg.Addr,
		Handler: handler,
	}

	// 监听 ctx 取消信号以优雅关闭
	go func() {
		<-ctx.Done()
		logger.Info().Msg("正在关闭 MCP HTTP 服务...")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := httpServer.Shutdown(shutdownCtx); err != nil {
			logger.Error().Err(err).Msg("MCP HTTP 服务关闭失败")
		}
	}()

	logger.Info().Str("addr", r.cfg.Addr).Msg("MCP Server 已启动")
	if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

// handleListMessages 处理 list_messages 工具调用
func (r *Runner) handleListMessages(ctx context.Context, _ *mcp.CallToolRequest, input listMessagesInput) (*mcp.CallToolResult, listMessagesOutput, error) {
	// 设置默认 limit
	limit := input.Limit
	if limit <= 0 {
		limit = 100
	}

	// 构建查询选项
	opts := &db.MessageTableListOptions{
		MessageType: input.MessageType,
		Sender:      input.Sender,
		Limit:       limit,
	}

	// 解析时间参数
	if input.CreatedAtGTE != nil {
		t, err := time.Parse(time.RFC3339, *input.CreatedAtGTE)
		if err != nil {
			return newToolError("created_at_gte 格式错误，需要 RFC3339 格式: " + err.Error()), listMessagesOutput{}, nil
		}
		opts.CreatedAtGTE = &t
	}
	if input.CreatedAtLTE != nil {
		t, err := time.Parse(time.RFC3339, *input.CreatedAtLTE)
		if err != nil {
			return newToolError("created_at_lte 格式错误，需要 RFC3339 格式: " + err.Error()), listMessagesOutput{}, nil
		}
		opts.CreatedAtLTE = &t
	}

	// 查询数据库
	entities, nextMarker, err := r.messageTable.List(ctx, input.Marker, opts)
	if err != nil {
		return nil, listMessagesOutput{}, err
	}

	// 转换为输出格式
	items := make([]messageItem, len(entities))
	for i, e := range entities {
		items[i] = messageItem{
			ID:               e.ID,
			Type:             string(e.Type),
			Attr:             string(e.Attr),
			Content:          e.Content,
			Sender:           e.Sender,
			SenderRemark:     e.SenderRemark,
			ChatType:         e.ChatType,
			ChatName:         e.ChatName,
			GroupMemberCount: e.GroupMemberCount,
			CreatedAt:        e.CreatedAt.Format(time.RFC3339),
		}
	}

	output := listMessagesOutput{
		Messages:   items,
		NextMarker: nextMarker,
	}

	// 序列化为 JSON 文本返回
	data, err := json.Marshal(output)
	if err != nil {
		return nil, listMessagesOutput{}, err
	}

	return &mcp.CallToolResult{
		Content: []mcp.Content{&mcp.TextContent{Text: string(data)}},
	}, output, nil
}

// newToolError 构造一个表示工具执行错误的 CallToolResult
func newToolError(msg string) *mcp.CallToolResult {
	return &mcp.CallToolResult{
		Content: []mcp.Content{&mcp.TextContent{Text: msg}},
		IsError: true,
	}
}

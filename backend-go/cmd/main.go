package main

import (
	"flag"
	"fmt"
	"os"

	"gopkg.in/yaml.v3"

	db "github.com/zhangzqs/wechat-message-summary/backend-go/internal/common/databases"
	"github.com/zhangzqs/wechat-message-summary/backend-go/internal/runner/mcpserver"
	"github.com/zhangzqs/wechat-message-summary/backend-go/internal/runner/wxautoconsumer"
	"github.com/zhangzqs/wechat-message-summary/backend-go/pkg/database"
	"github.com/zhangzqs/wechat-message-summary/backend-go/pkg/runner"
	"github.com/zhangzqs/wechat-message-summary/backend-go/pkg/zerologger"
)

// AppConfig 是应用的顶层配置
type AppConfig struct {
	Logger         zerologger.Config    `yaml:"logger"`
	Database       database.Config      `yaml:"database"`
	WxAutoConsumer wxautoconsumer.Config `yaml:"wxautoconsumer"`
	MCPServer      mcpserver.Config     `yaml:"mcpserver"`
}

func main() {
	configPath := flag.String("config", "config.yaml", "配置文件路径")
	flag.Parse()

	// 加载配置
	cfg, err := loadConfig(*configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "加载配置失败: %v\n", err)
		os.Exit(1)
	}

	// 初始化日志
	logger := zerologger.MustNewLogger(&cfg.Logger)

	// 初始化数据库
	gormDB, err := database.Open(&cfg.Database)
	if err != nil {
		logger.Fatal().Err(err).Msg("初始化数据库失败")
	}

	// 自动迁移表结构
	rawDB, _ := gormDB.DB()
	if rawDB != nil {
		defer rawDB.Close()
	}
	if err := gormDB.AutoMigrate(&db.MessageEntity{}); err != nil {
		logger.Fatal().Err(err).Msg("数据库迁移失败")
	}

	// 初始化数据访问层
	messageTable := db.NewMessageTable(gormDB)

	// 启动所有 Runner
	runner.Run(
		*logger.Logger,
		wxautoconsumer.New(&cfg.WxAutoConsumer, messageTable),
		mcpserver.New(&cfg.MCPServer, messageTable),
	)
}

// loadConfig 从 YAML 文件加载配置
func loadConfig(path string) (*AppConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取配置文件 %s 失败: %w", path, err)
	}

	var cfg AppConfig
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("解析配置文件失败: %w", err)
	}
	return &cfg, nil
}

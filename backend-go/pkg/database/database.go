package database

import (
	"errors"
	"fmt"

	"gorm.io/driver/postgres"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// Config 是数据库连接配置
type Config struct {
	Driver string `yaml:"driver"` // 数据库驱动类型：sqlite 或 postgres
	DSN    string `yaml:"dsn"`    // 数据源名称（连接字符串）
}

func (c *Config) Validate() error {
	if c.Driver == "" {
		return errors.New("database driver is required")
	}
	if c.Driver != "sqlite" && c.Driver != "postgres" {
		return fmt.Errorf("unsupported database driver: %s (supported: sqlite, postgres)", c.Driver)
	}
	if c.DSN == "" {
		return errors.New("database dsn is required")
	}
	return nil
}

// Open 根据配置打开数据库连接
func Open(cfg *Config) (*gorm.DB, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid database config: %w", err)
	}

	var dialector gorm.Dialector
	switch cfg.Driver {
	case "sqlite":
		dialector = sqlite.Open(cfg.DSN)
	case "postgres":
		dialector = postgres.Open(cfg.DSN)
	}

	db, err := gorm.Open(dialector, &gorm.Config{})
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}
	return db, nil
}

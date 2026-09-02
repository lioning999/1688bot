-- ============================================================
-- Sourcely V1 — 数据库 Schema
-- 引擎: MySQL 8.0 / InnoDB / utf8mb4
-- 日期: 2026-07-21
-- ============================================================

CREATE DATABASE IF NOT EXISTS sourcely_DB
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE sourcely_DB;

-- ============================================================
-- 1. users — Google / Telegram 登录用户（多身份，单用户表）
--    已有库迁移：ALTER TABLE users
--      MODIFY google_id VARCHAR(100) NULL UNIQUE,
--      ADD COLUMN telegram_uid VARCHAR(50) NULL UNIQUE AFTER google_id;
-- ============================================================
CREATE TABLE users (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  google_id   VARCHAR(100) NULL UNIQUE COMMENT 'Google sub claim，bot 用户为空',
  telegram_uid VARCHAR(50) NULL UNIQUE COMMENT 'Telegram user_id，bot 用户身份',
  email       VARCHAR(200) COMMENT 'Google 账号邮箱，可空',
  name        VARCHAR(200) COMMENT 'Google 账号显示名',
  avatar_url  VARCHAR(500) COMMENT 'Google 头像 URL',
  created_at  DATETIME DEFAULT NOW(),
  last_login  DATETIME DEFAULT NOW() COMMENT '每次登录更新',
  tier        VARCHAR(20) NOT NULL DEFAULT 'free' COMMENT 'free|paid',
  quota       INT NOT NULL DEFAULT 10 COMMENT '剩余分析次数',
  last_reset_date DATE DEFAULT NULL COMMENT '上次配额补充日期，用于懒重置',
  default_lang VARCHAR(5) DEFAULT NULL COMMENT '用户默认语言 en/vi/th/zh'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Google/Telegram 登录用户';

-- ============================================================
-- 2. analysis — 分析记录（主表）
--    V1.3：列字段只保留历史列表展示所必需 + 系统字段。
--         完整分析数据（原始 raw_json + 翻译 display_i18n）。
-- ============================================================
CREATE TABLE analysis (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  user_id         INT NOT NULL,
  offer_id        VARCHAR(30) NOT NULL COMMENT '1688 offerId',
  status          ENUM('pending','running','done','failed') DEFAULT 'pending' COMMENT '分析状态',

  -- 历史列表展示列（避免每次 JSON_EXTRACT）
  title           VARCHAR(500) COMMENT '商品标题',
  image_url       TEXT COMMENT '商品主图URL',
  price_min       DECIMAL(10,2) COMMENT '最低单价',
  price_max       DECIMAL(10,2) COMMENT '最高单价',

  -- 分析追踪
  apify_task_id   VARCHAR(50) COMMENT 'Apify 任务 ID',

  -- 完整数据
  raw_json        MEDIUMTEXT COMMENT 'Apify 原始返回 JSON（唯一数据源，不可丢）',
  display_i18n    TEXT COMMENT '翻译后 display JSON {lang: display}。分析时只存当前语言，切语言时懒加载追加',
  favorited       TINYINT(1) DEFAULT 0 COMMENT '收藏状态 0=未收藏 1=收藏（收藏后不参与 FIFO 自动清理）',

  -- 时间戳
  created_at      DATETIME DEFAULT NOW(),
  updated_at      DATETIME DEFAULT NOW() ON UPDATE NOW(),

  UNIQUE KEY uk_offer_user (offer_id, user_id) COMMENT '同一用户不重复分析同一商品',
  KEY idx_user (user_id),
  KEY idx_status (status),
  KEY idx_created (created_at),
  FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='商品分析记录';
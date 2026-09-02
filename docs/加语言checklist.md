# 加语言 Checklist（防 ru 式踩坑）

> 触发：新增任何语言（ar/ko/...）时，先读本文。
> 来源：ru 落地踩坑复盘（2026-09-01）——价格 FX 不生效 + 验厂维度翻译撞车 + 数字格式未本地化。
> 配套：[技术-新增俄语支持方案.md](技术-新增俄语支持方案.md) = ru 这次的具体落点实例，本文 = 通用方法。

---

## 一句话

**代码对 ≠ 生效。** 加语言要改 6 组联动点，改完必须 【重启进程】 + 【清缓存】 + 【跑测试】 才算完。

---

## 两个致命坑（代码对了也不生效）

| 坑 | 症状 | 解法 |
|----|------|------|
| **进程不重启**（uvicorn 非 reload 模式） | 改后价格/维度名仍是旧值 | 改后端代码后必须重启进程 |
| **`display_i18n` DB 缓存命中** | 命中旧 build，新代码不执行 | 清测试 offer 缓存：`UPDATE analysis SET display_i18n=NULL WHERE offer_id='<测试offer>'`（保留 raw_json 可跳过 Apify 重建） |

---

## 三层防线

| 层 | 手段 | 防什么 |
|----|------|-------|
| 🧠 机器强制 | `tests/test_builder.py` 断言非 zh 价格已换算 | 汇率/货币分支漏配 |
| 📖 操作清单 | 本文 6 步 | 联动点漏一处 |
| 🧭 AI 入口 | 根 `CLAUDE.md` 文档索引「加语言 → 本文档」 | AI 不知道有本文档 |

---

## 联动点清单（6 组）

| 组 | 文件 |
|----|------|
| ① 翻译数据 | `src/api/domain/data/glossary.json` · `src/api/domain/display/verdict_prompts.json` · `src/chrome-ext/lang/{lang}.json` · `src/bot/lang/{lang}.json` |
| ② 前端 i18n | `src/chrome-ext/lib/i18n.js`（LOCALES + supported）· `src/chrome-ext/sidepanel.html` 语言切换 |
| ③ 后端白名单（safe_lang 5 处） | `builder.py:76` · `analyze_svc.py:150/288/331/429` · `routes/auth.py:147` · `ai_verdict_svc.py:84` |
| ④ 货币 | `ai_verdict_svc.py:_make_money()` · `config.py` `FX_*` · `.env` · `.env.example` |
| ⑤ 判词 prompt | `verdict_prompts.json`（母语 system prompt + 催促词数组） |
| ⑥ bot | `src/bot/lang/{lang}.json`（bot 支持该语言时） |

---

## 6 步操作顺序

1. 翻译数据（组①）
2. 前端 i18n（组②）
3. 后端白名单（组③）
4. 货币 + 判词 prompt（组④⑤）
5. **重启后端进程** + **清测试 offer 的 `display_i18n` 缓存**
6. **跑测试**：`tests/test_builder.py` + 现有回归；验证价格 ≠ CNY 原值、维度名/数字格式已本地化

---

## 验证要点

- `price.low/high` 已按 `per_cny` 换算（非 zh 语言）
- 维度名/数字格式本地化（ru 千分位用空格、逗号小数位）
- 前端 4 语言切换正常
- glossary 中文原文改动 → 同步 4 语言翻译（铁律九）

---

## 文档同步（执行时）

- `docs/README.md` 索引
- 根 `CLAUDE.md` 文档索引表
- `.claude/skills/file-map/SKILL.md`：`lang/{zh,en,vi,th}.json` → 加新语言

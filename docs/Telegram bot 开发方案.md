# Telegram bot 开发方案

> 状态：草案 · 配套：[Telegram bot 需求文档.md](Telegram bot 需求文档.md) · 目标：开发不出问题

---

## 一、目标与范围

- 复用现有后端：Apify 抓取 → 规则引擎判分 → AI 判词 → display JSON，**核心管线零改动**
- bot 独立进程，只走 HTTP 调 API，不碰 DB
- 仅俄语（ru），人工收款，免费/会员配额
- 插件功能**零回归**

## 二、总体架构

```
用户 ──▶ bot 进程 (src/bot/ 独立目录, polling)
              │ HTTP (带 JWT)
              ▼
         后端 API /api/analyze（现有，不改）
              │
              ▼
         MySQL（bot 不碰）
```

**关键原则：**
1. 所有改动 = 加法，删除 0
2. middleware 不改（现有可选认证已支持 bot 的 JWT）
3. bot 目录与 `src/api/` 零交集

---

## 三、改造流程与顺序（5 阶段，每阶段独立可测）

### 阶段 0：前置确认（已完成）

| 项 | 结论 |
|----|------|
| 定位 users 建表 SQL | ✅ 在 `src/api/db/schema.sql`（**不是** `db/`，CLAUDE.md/file-map 该处过时）。⚠️ `google_id` 是 `NOT NULL UNIQUE` → bot 用户无 google，**必须先改可空** |
| 确认 main.py 路由注册方式 | ✅ `app.include_router()`（main.py:136-143）。bot_auth = 新建 `routes/bot_auth.py` → import + include；中间件 `EXEMPT_PREFIXES` 加 `/api/bot` |
| 配置 bot token 到 `.env` | ✅ 已配置 `TELEGRAM_BOT_TOKEN`（上线后再到 BotFather 换新，旧 token 已泄漏） |
| 抽样 ru 判词 | ✅ 词库 ru 翻译自然 + ru prompt 已存在；Qwen 真机输出质量 → 阶段 2 首跑签收 |

### 阶段 1：后端地基（纯加法）

| 步骤 | 改什么 | 验证 |
|------|--------|------|
| 1-1 | `src/api/db/schema.sql`：users 表 `google_id` 改可空（bot 无 google）+ 加 `telegram_uid`（可空唯一）；无需 expiry | ALTER 成功，旧数据无影响 |
| 1-2 | `user_repo.py`：+`get_by_telegram_uid`/`create_by_telegram`（照抄 google 版）；付费开通复用现有 `add_quota` | 单测通过 |
| 1-3 | `config.py`+`.env.example`：+`BOT_SECRET`（bot 鉴权密钥）+ `PAID_ONETIME_QUOTA=300`（付费一次性开通配额）；`DAILY_FREE_QUOTA=3` 已有复用。**所有数值走 Config，禁止硬编码** | `Config.validate()` 不炸 |
| 1-4 | 新增 `routes/bot_auth.py`：`POST /api/bot/login`（secret+telegram_uid → 取/建用户 → 签发 JWT）；注册进 main.py；加进 EXEMPT_PATHS | curl 拿 JWT → 调 analyze 成功 |
| 1-5 | `auth_svc.py`：付费 300 配额跳过每日补地板（一次性不重置） | 现有测试全绿（回归） |

### 阶段 2：bot 最小闭环（✅ 已完成，待真机联调）

| 步骤 | 做什么 | 状态 |
|------|--------|------|
| 2-1 | `src/bot/`：config(读 env) + `bot.py`(polling) | ✅ |
| 2-2 | `/start` 欢迎语 | ✅ |
| 2-3 | 识别 1688 链接 → `POST /api/analyze` → 轮询 `GET /{task_id}` → 渲染 ru 报告 | ✅ |
| 2-4 | 手动测：发链接 → 90 秒内收到俄语报告 | ⏳ 真机联调（阶段 2-4 首跑） |

> **决策记录：** 原计划用 `python-telegram-bot`，实际**零新增依赖** — 直接用 `httpx`（后端环境已有）调 Telegram Bot API 长轮询（getUpdates + 手动 offset）。理由：铁律三避免引入当前不需要的第三方依赖；Bot API 本身是简单 HTTP。阶段 3 按钮用 sendMessage 的 reply_markup JSON 即可。若后续要对话框架再切 python-telegram-bot，只换 bot.py 轮询层。
>
> **bot 目录文件：** `config.py`（读共享 src/api/.env）/ `bot.py`（长轮询+分发）/ `backend.py`（HTTP+JWT 缓存）/ `render.py`（display→ru HTML，纯函数）/ `i18n.py`（合并 bot 文案 + 共享 msg.* 翻译，唯一来源 chrome-ext/lang/ru.json）/ `lang/ru.json`。

> **报告方案（2026-08-31 智囊团拍板）：** 报告 = **2 条消息**，分析完成**自动连发**（用户零点击）。
> - **第 1 条** `sendPhoto`：产品图 + caption（标题/价格/MOQ/销量/**Summary 结论**）— caption 上限 1024，挂 [查看商品]
> - **第 2 条** `sendMessage`：完整验证（产品验证+供应商验证，≤4096），底部挂 [查看商品][拿样品]
> - 间隔 0.5–1s 防粘包；**降级**：图拉不到 → 第 1 条退化纯文本卡片，第 2 条照发（保证全量内容）
> - **内容/布局 = 对齐插件显示**（sidepanel.js 渲染结构：标题→价格+单位→MOQ→销量→Summary→产品验证6维+库存+verdict→供应商验证3维+公司+产业带+verdict），不是 display JSON 原样
> - **价格格式 = 俄式**：₽ 在后带空格、千分位用空格（俄语逗号是小数位）、有小数才用逗号
> - **拿样区/PRO = 移出报告正文** → 菜单；报告只放审查内容
> - 维度行一行式：`✔ icon 名称: 数据 (标杆)`（长值自然换行，靠冒号不乱）；✔ 信任项在前、✘ 风险集中尾部 + ⚠️ 分组标题

### 阶段 3：会员/配额/人工收款

| 步骤 | 做什么 |
|------|--------|
| 3-1 | 配额用完提示 + [开通 PRO][联系客服] 按钮 |
| 3-2 | 付款状态机：我已付款 → 待确认 → 开通成功 |
| 3-3 | admin 后台：给用户 +300（`add_quota(Config.PAID_ONETIME_QUOTA)`，不硬编码 300） |
| 3-4 | 模拟走通：付款 → 运营开通 → bot 推送 |

### 阶段 4：增强（✅ 已拍板方案，见上方「报告方案」块）

- 报告重排版：**内容/布局对齐插件** + 2 条消息（图+结论 / 完整验证）+ 产品图 `sendPhoto`
- 价格格式改俄式（₽ 在后、空格千分位、逗号小数）
- 菜单体系：底部常驻 reply keyboard（查供应商/拿样品/PRO/帮助）+ 报告底部 inline 按钮（查看商品/拿样品）+ `callback_query` 分发
- 拿样区/PRO 从报告正文移入菜单（阶段 4 细做拿样流程，阶段 3 做 PRO 开通）
- 300 次用完提醒、心跳监控

### 阶段 5：部署

systemd（`Restart=always` + 日志）+ 环境变量 + 心跳告警

---

## 四、开发注意事项（防坑）

1. **消息解析转义**：商品名/规格里常有 `_` `*` `[` 等特殊字符，Telegram parse_mode 下不转义会直接报错 → 渲染统一走 HTML 转义函数
2. **JWT 缓存**：bot 内存缓存 telegram_uid→JWT，收到 401 自动重登录，别每次请求都登录
3. **轮询上限**：间隔 2-3 秒、最长 90 秒，超时给用户"分析超时请重试"
4. **telegram_uid 并发首触**：两个请求同时建用户 → 唯一索引 + 捕获 DuplicateKey 重查，防重复注册
5. **secret 安全**：比对用恒定时间比较；不 log；不进响应体
6. **每阶段跑现有测试**：回归不通过不进下一阶段
7. **改过的名字/常量 grep 全项目**（铁律四）；新增文件注册 main.py + file-map

---

## 五、风险规避（映射到措施）

| 风险 | 规避措施 | 阶段 |
|------|---------|------|
| bot token 泄漏 | **立刻换 token**，密钥只进 env | 0 |
| 多号薅配额 | 免费=每天 3 次，先观察账单，异常再收紧 | 3 |
| 双鉴权攻击面 | bot 也走 JWT，中间件零改动（一套校验器） | 1 |
| 契约漂移 | 后端只出 display JSON，bot 缺字段自己拼 | 2 |
| ru 质量不稳 | 上线前抽样 5 条核对 | 0 |
| bot 单点 | systemd 自动重启 + 心跳 | 5 |
| 改了插件挂 | 每阶段跑回归测试 | 全程 |

---

## 六、回滚方案

全部是加法 → 回滚 = `git revert` 对应提交；DB 新列可空，删列对旧数据无影响（或保留无害）。

---

## 七、已拍板事项

1. 免费策略：**每天 3 次**（每日重置）
2. bot token：先配置到 `.env` 使用，上线后再到 BotFather 换新（旧 token 已泄漏）
3. 付费模型：**一次性 +300 次，不限时间**，admin 复用现有 `add_quota`
4. 报告方案：**2 条消息自动连发**（图+结论 / 完整验证），内容/布局对齐插件显示，价格俄式格式
5. 拿样区/PRO：**移出报告正文，进菜单**（底部常驻 reply keyboard + 报告底部 inline 按钮）
6. 维度行一行式排版（`✔ 名称: 数据 (标杆)`），✔ 信任项在前、✘ 风险集中尾部 + ⚠️ 分组标题

## 节点索引

> 排查/改代码时先查这张表，再跳到对应节点。节点名在正文里可直接搜索。

| 节点 | 职责 | 文件 · 方法 | 关键动作 |
|------|------|-------------|---------|
| 节点 1 | 启动分析 | routes/analyze.py · `analyze_start` | 校验URL → 提取offer_id → 全局限流 → 配额 → 启动后台 |
| 节点 2 | 后台任务编排 | services/analyze_svc.py · `start()` | 失败检查 → 请求合并 → 扣配额 → 建 Task |
| 节点 3 | 后台流水线 | services/analyze_svc.py · `_run()` | ↓ 见子节点 |
| 　3.1 | DB 检查复用 | repositories/analysis_repo.py · `get_by_offer_id` | 查 raw_json + display_i18n |
| 　3.2 | Apify 抓取 | adapters/apify_adapter.py · `fetch_product_by_url` | 90s 超时 |
| 　3.3 | 清洗+标准化 | domain/data/mapper.py · `map_raw` | 字段级容错 |
| 　3.4 | 规则引擎 | domain/evaluate/ · `evaluate_product/supplier/summary` | 12 规则 → 4 档 grade |
| 　3.5 | 构建 Display+翻译 | services/ai_verdict_svc.py · `build_result_with_display` | zh 模板 / 非zh AI |
| 　3.6 | 自动落库 | services/analyze_svc.py · `_save_to_db_upsert` | INSERT ... ON DUPLICATE |
| 　3.7 | 超限清理 | repositories/analysis_repo.py · `cleanup_excess` | FIFO 删未收藏 |
| 节点 4 | 轮询状态 | routes/analyze.py · `analyze_status` | pending/done/failed |
| 节点 5 | 默认语言 | routes/auth.py · `PUT /api/user/lang` | 改语言写 DB |

> 📖 判词定档规则（产品 12 规则→4 档 · 供应商 6 规则→4 档 · 综合 9 档）见文末「判词档位设计」。
> 💾 缓存规则：DB `display_i18n` 是唯一缓存，全项目禁止内存缓存层（DB 命中检查在前，内存缓存永远读不到）。

---

用户输入 1688 链接 + 选语言（如 en）
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 节点 1 — routes/analyze.py  POST /api/analyze               │
│                                                             │
│ 目的：门卫 + 放行                                            │
│   校验请求合法 +全局限流+ 配额够 → 立刻返回 task_id，不等分析结果      │
│                                                             │
│ 输入：                                                       │
│   url   = 1688 商品链接（必填，Pydantic 校验格式）            │
│   lang  = 目标语言 en/vi/th/zh，空串 = zh（V1 不翻译）       │
│                                                             │
│ 做了什么：                                                   │
│   1. 校验 URL 是 1688 链接（Pydantic validator，进路由前）    │
│      → is_valid_1688_url() 拦截非法格式                      │
│   2. 提取 offer_id（extract_offer_id）                       │
│      → 校验纯数字 + 长度 ≥ 8，否则 ValidationError            │
│        （OFFER_ID_NOT_FOUND / OFFER_ID_INVALID）             │
│   3. 全局限流检查（rate_limiter.check()）                     │
│      → 超限 → GLOBAL_RATE_LIMIT（retry_after 60秒）          │
│   4. 用户配额检查（user_repo.get_quota_info）                 │
│      → 取 user_id（request.state.user_id，JWT 中间件注入）    │
│      → 查 quota / tier / last_reset_date                     │
│      → 懒重置补地板：为空/过期 → lazy_reset_daily_quota       │
│        （补到 Config.DAILY_FREE_QUOTA / DAILY_PAID_QUOTA）   │
│      → quota ≤ 0 → QUOTA_EXHAUSTED                           │
│   5. 启动后台分析（analyze_service.start）                    │
│      → 扣配额在 start() 内执行，请求合并后统一处理            │
│                                                             │
│ 输出：{ task_id, status: "pending" }  ← 立即返回，不等结果    │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 节点 2 — services/analyze_svc.py  AnalyzeService.start()    │
│                                                             │
│ 目的：编排后台任务                                            │
│   立即返回 task_id，分析扔后台跑，不卡住前端                  │
│                                                             │
│ 输入：                                                       │
│   offer_id = 节点1 提取的商品编号                            │
│   user_id  = JWT 注入的用户 ID                              │
│   raw_url  = 原始 1688 链接                                  │
│   lang     = 目标语言 en/vi/th/zh                           │
│                                                             │
│ 做了什么：                                                   │
│   1. 失败次数检查（同 offer_id 连续失败 ≥3 次 → 拒绝）        │
│   2. 请求合并检查（同 offer_id 正在跑 → 复用旧 Task）         │
│      → 防止：用户等 Apify 返回期间（10-90秒）重复点击          │
│         同一商品，避免多次调用 Apify（花钱）+ 重复跑流水线      │
│   3. 扣减配额（user_repo.decrement_quota）                   │
│   4. 创建后台 asyncio.Task → 调用 _run()                     │
│      → POST /api/analyze 必须立即返回 task_id 给前端，        │
│         不能卡住等 Apify 跑完。把 _run() 扔后台异步执行，      │
│         前端拿 task_id 每 2 秒轮询，Task 跑完状态变 done       │
│                                                             │
│ 输出：task_id                                                │
└─────────────────────────────────────────────────────────────┘
        │
        ▼  （后台异步执行）
┌─────────────────────────────────────────────────────────────┐
│ 节点 3 — services/analyze_svc.py  AnalyzeService._run()     │
│                                                             │
│ 子节点 3.1 — DB 检查（复用 raw_json + display_i18n）         │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 文件：repositories/analysis_repo.py                  │   │
│   │ 方法：get_by_offer_id(offer_id, user_id)             │   │
│   │                                                     │   │
│   │ 目的：复用已分析商品，避免重复调 Apify（花钱）         │   │
│   │                                                     │   │
│   │ 输入：offer_id + user_id（per-user 隔离）            │   │
│   │                                                     │   │
│   │ 做了什么：                                           │   │
│   │   SQL: SELECT raw_json, display_i18n                 │   │
│   │        FROM analysis                                │   │
│   │        WHERE offer_id=? AND user_id=?                │   │
│   │          AND status='done'                           │   │
│   │                                                     │   │
│   │ 输出（三级判断，三选一）：                            │   │
│   │   ① 没查到 → 走 3.2 Apify 抓取                       │   │
│   │   ② 有当前语言 → 直接返回 display_i18n                │   │
│   │      （0 次 AI，跳过 Apify+mapper+judge）  退配额           │   │
│   │      → 同用户同商品同语言，上次已翻好，没必要重跑     │   │
│   │   ③ 有 raw_json 无当前语言 → 跳过 Apify  退配额             │   │
│   │      → 走 3.3 mapper+judge+翻译，重建 + 追加语言      │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
│ 子节点 3.2 — Apify 抓取（仅 DB 无 raw_json 时）              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 文件：adapters/apify_adapter.py                      │   │
│   │ 方法：fetch_product_by_url(1688链接)                  │   │
│   │                                                     │   │
│   │ 目的：抓取商品原始数据（唯一数据源）                   │   │
│   │                                                     │   │
│   │ 输入：1688 商品链接                                   │   │
│   │                                                     │   │
│   │ 做了什么：                                           │   │
│   │   fetch_product_by_url 抓取，超时 90 秒              │   │
│   │   失败 → 退配额 + 记录失败次数                        │   │
│   │                                                     │   │
│   │ 输出：原始 raw_json                                  │   │
│   │   （标题/价格/图片/供应商/规格/SKU/销量）             │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
│ 子节点 3.3 — 数据清洗 + 标准化                                │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 文件：domain/data/mapper.py                          │   │
│   │ 方法：map_raw(raw, original_url, offer_id)            │   │
│   │                                                     │   │
│   │ 做什么：把 Apify 原始 JSON 转成项目内部标准格式          │   │
│   │                                                     │   │
│   │ ① 清洗：字段级容错，取值前检查存在性，缺字段不崩溃       │   │
│   │    · 百分比 "95.3%" / 0.953 / 95.3 → 统一转 float     │   │
│   │    · 非法数值 → 0 或 None，不抛异常                    │   │
│   │                                                     │   │
│   │ ② 标准化：Apify 原始字段名 → 项目内部字段名             │   │
│   │    · price.min/max             → priceCNY {low, high} │   │
│   │    · supplier.flags            → factoryFlags 中文标签 │   │
│   │    · supplier.flags + tpYear   → dataTier 三层金字塔   │   │
│   │    · supplier.stats.repeatRate → repurchase 复购率    │   │
│   │    · shipping.location         → industryCluster 产业带│   │
│   │    · quantityPrices[]          → price_tiers 阶梯价   │   │
│   │    · productFlags+serviceLabels → badgeLabels 标签    │   │
│   │    · specs[]                   → 过滤关键规格(材质/品牌)│   │
│   │    · supplier.sellerType+flags → trustBar label      │   │
│   │                                                     │   │
│   │                                                     │   │
│   │ ③ 为什么能取对位置（两层保障）：                         │   │
│   │    第1层 Apify Actor：不同商品类型（普通/加工定制/跨境）   │   │
│   │      已映射成统一 schema，price/supplier 等 key 保证在位   │   │
│   │    第2层 多路 fallback：少量字段在不同类型里位置不同       │   │
│   │      例如复购率 _parse_repurchase 三条路依次尝试：        │   │
│   │      路径1 supplier.stats.repeatRate（大部分商品）        │   │
│   │      路径2 root.repurchaseRate（部分商品在根层级）        │   │
│   │      路径3 supplier.factoryTags 遍历找"回头率"（兜底）    │   │
│   │      三路都没取到 → 返回 None，不崩                      │   │
│   │                                                     │   │
│   │ 输入：Apify 原始 JSON（无结构保证）                     │   │
│   │ 输出：标准化 dict，50+ 字段，每个字段都有默认值          │   │
│   │ 纯函数，零外部依赖，不调 DB 不调 API                    │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
│ 子节点 3.4 — 规则引擎评判（验货报告三卡片，程序定档）        │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 文件：domain/evaluate/                                │   │
│   │   _product.py    evaluate_product（6 维 → 12 规则）    │   │
│   │   _supplier.py   evaluate_supplier（3 维 → 6 规则）    │   │
│   │   evaluator.py   evaluate_summary（9 档矩阵）          │   │
│   │                                                     │   │
│   │ 输入：3.3 mapper 产出的 mapped dict（~50字段）         │   │
│   │                                                     │   │
│   │ 做什么：程序定档（规则引擎判断），不产最终文案           │   │
│   │   ① 产品：6 维信号 → 12 规则 → tier → grade            │   │
│   │   ② 供应商：3 维信号 → 6 规则 → tier → grade            │   │
│   │   ③ 综合：产品档 × 供应商档 → 9 档矩阵 → headline       │   │
│   │                                                     │   │
│   │ 输出（验货报告三卡片，塞进 display JSON）：             │   │
│   │   productEval  {score, grade, dimensions[6], verdict} │   │
│   │   supplierEval {score, grade, dimensions[3], verdict} │   │
│   │   summaryLine  {headline, reason, verdict}            │   │
│   │                                                     │   │
│   │ 三层「档」：规则（产品12 / 供应商6）→ tier（细分档）     │   │
│   │   → grade（粗档 go/ok/bad/none，给前端染色）           │   │
│   │                                                     │   │
│   │ 由 3.5 build_display 调用；grade 前端染色，            │   │
│   │ 判词文字 zh 走 glossary、非 zh 走 Qwen 润色             │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
│ 子节点 3.5 — 构建 Display + 翻译                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 文件：services/ai_verdict_svc.py                      │   │
│   │ 方法：build_result_with_display(mapped, offer_id, lang)│   │
│   │                                                     │   │
│   │ 输入：mapped dict（3.3数据 + 3.4判词KEY，合在一起的）   │   │
│   │                                                     │   │
│   │ 输出：mapped dict + display 字段                       │   │
│   │   display = {title, images, price, trustBar, badges,  │   │
│   │              specs, sales, priceTiers,                 │   │
│   │              factory, productEval, supplierEval,       │   │
│   │              summaryLine}  ← 前端 5 卡片结构            │   │
│   │                                                     │   │
│   │ ── build_display() 内部的 3 路拆分 ──                  │   │
│   │   路① 数字/URL → 直接输出                              │   │
│   │     price{low,high,moq} images priceTiers offerId     │   │
│   │     不调 AI，天然语言无关                               │   │
│   │   路② 判词/术语 → glossary.json 查表                   │   │
│   │     verdict text trustBar label badges sales explain  │   │
│   │     tier label stock level 等                         │   │
│   │     5 语言预翻译，查表填参，不调 AI                      │   │
│   │   路③ 1688中文原文 → 待翻译                             │   │
│   │     title specs supplierName                         │   │
│   │     zh 保留中文 / en vi th 调 Qwen 翻译                │   │
│   │                                                     │   │
│   │ ── 两条路径 ──                                        │   │
│   │                                                     │   │
│   │ 路径 A：lang=zh                                       │   │
│   │   build_display(mapped, "zh")                        │   │
│   │   路③中文原文保留 → 不调 Qwen，纯 CPU，秒出             │   │
│   │                                                     │   │
│   │ 路径 B：lang=en/vi/th（非中文，一次 Qwen 调用出一语言）     │   │
│   │   ① build_display(mapped, lang) → 出模板 display（兜底）     │   │
│   │      · 路①数字直出 ✅  路② glossary 查表 ✅                   │   │
│   │      · 路③ title/supplierName/判词还是中文 ⚠️                 │   │
│   │      · 判词 glossary en/vi/th 大量 "TODO" → 降级显示中文     │   │
│   │                                                             │   │
│   │   ② system prompt：每种语言独立的母语 prompt                     │   │
│   │      · verdict_prompts.json → _VP_AI[lang].system              │   │
│   │      · vi 用越南语写、th 用泰语写、en 用英语写                    │   │
│   │      · 市场习惯直接融入 prompt 正文（Shopee怕差评/Zalo/LINE等）   │   │
│   │      · Qwen 用目标语言思考 → 输出天然地道，无翻译腔               │   │
│   │                                                             │   │
│   │   ③ 调 Qwen，一次调用只出当前语言，传入 9 块上下文（pack_ai_input）：│   │
│   │      · conclusion（产品/供应商/综合 tier + 语气）             │   │
│   │      · must_mention（产品事实：销量/复购/价格/好评...）       │   │
│   │      · supplier_must_mention（供应商事实：身份/认证/年限）    │   │
│   │      · must_not_say（产品禁止表述）                           │   │
│   │      · supplier_must_not_say（供应商禁止表述）                │   │
│   │      · action（推荐行动：拿样/比价/跳过...）                  │   │
│   │      · context（试错成本 + 供应商摘要 + 市场备注）            │   │
│   │      · dimensions（9 个维度 English 数据）                    │   │
│   │      · to_translate（title + supplierName 原始中文）         │   │
│   │                                                             │   │
│   │   ④ Qwen 返回 JSON，取 5 个字段：                            │   │
│   │      · translated_title          → 替换 display.title       │   │
│   │      · translated_supplier_name  → 替换 factory.supplierName│   │
│   │      · product_verdict  → 替换 productEval.verdict          │   │
│   │      · supplier_verdict → 替换 supplierEval.verdict         │   │
│   │      · summary_verdict  → 替换 summaryLine.verdict          │   │
│   │                                                             │   │
│   │   ⑤ 逐字段校验（validate_ai_output）：                        │   │
│   │      判词中的数字必须与 dimensions 真实数据一致 → 不对就降级  │   │
│   │      禁止表述出现 → 降级                                     │   │
│   │      单个字段校验失败 → 该字段用步骤①的 glossary 模板         │   │
│   │                                                             │   │
│   │   ⑥ 降级链：Qwen调用失败/JSON解析失败 → 全部用步骤①模板       │   │
│   │      单字段校验失败 → 单字段降级 glossary                     │   │
│   │      glossary 也没有 → 显示中文原文（至少不是空白）           │   │
│   │                                                             │   │
│   │   ⑦ 判词带上 _aiGenerated=lang 标记（不泄漏到前端）          │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
│ 子节点 3.6 — 自动落库                                        │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 文件：services/analyze_svc.py  _save_to_db_upsert()   │   │
│   │       repositories/analysis_repo.py  upsert()         │   │
│   │                                                     │   │
│   │ 写入 analysis 表：                                    │   │
│   │   raw_json     = Apify 原始 JSON 字符串               │   │
│   │   display_i18n = {"en": {完整display JSON}}           │   │
│   │   title / image_url / price_min / price_max          │   │
│   │                                                     │   │
│   │ SQL: INSERT ... ON DUPLICATE KEY UPDATE              │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
│ 子节点 3.7 — 超限清理                                        │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 文件：repositories/analysis_repo.py  cleanup_excess() │   │
│   │ 超过上限 → 删最早未收藏记录（FIFO）                    │   │
│   └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 节点 4 — routes/analyze.py  GET /api/analyze/{task_id}      │
│                                                             │
│ 前端每 2 秒轮询                                              │
│ status=pending → 继续等                                      │
│ status=done    → result 含 display JSON（缓存命中）或 mapped+display（新建）│
│ status=failed  → error 里有错误信息                          │
└─────────────────────────────────────────────────────────────┘

---

## 节点 5 — 用户默认语言（default_lang）

> ⚠️ 本节点与节点 1-4 的分析管线独立，互不影响。

### 规则（一句话）

**改语言就写 DB，不改就不写。** DB 和 JWT 永远一致。

### 流程

```
用户首次登录（Google OAuth）
  ├─ 新用户 → INSERT users.default_lang = 插件当前语言
  ├─ 老用户 → 不冲突不改（已有 default_lang）
  └─ 签发 JWT，payload 含 default_lang
        │
        ▼
  SW 解码 JWT → chrome.storage.local { sourcely_lang }
        │
        ▼
  I18N.detect() → 恢复语言

─────

用户切语言（插件 UI 点语言切换）
  └─ PUT /api/user/lang { lang: "vi" }
       └─ UPDATE users SET default_lang = 'vi'
            └─ 下次登录 JWT 自然是 'vi'

─────

用户不切语言
  └─ 什么都不动
       └─ 下次登录 JWT 还是原值
```

### 涉及文件

| 层 | 文件 | 改动 |
|----|------|------|
| DB | `schema.sql` | `users` 表加 `default_lang VARCHAR(5)` |
| 后端 | `utils/jwt.py` | `create_token()` payload 加 `default_lang` |
| 后端 | `repositories/user_repo.py` | `create()` 接受 `default_lang`；`get_by_google_id()` SELECT 加列 |
| 后端 | `services/auth_svc.py` | `login_with_google()` 新用户写 default_lang，JWT 带出 |
| 后端 | `routes/auth.py` | `google_login` 收 `lang` 参数编码进 state |
| 后端 | `routes/auth.py` | 新增 `PUT /api/user/lang` |
| 插件 | `service-worker.js` | LOGIN 前传 lang，LOGIN 后解码 JWT 恢复语言；新增 `SET_LANG` 消息 |
| 插件 | `lib/api.js` | 加 `setLang(lang)` |
| 插件 | `lib/i18n.js` | `switchTo()` 加 `API.setLang(lang)` |

### 与节点 1-4 的关系

**零影响。** 语言偏好存储不改分析管线的任何逻辑。节点 1 的 `lang` 参数来自插件当前语言（`I18N.getLang()`），与 `default_lang` 无关。`default_lang` 只决定「下次登录后插件初始语言是什么」。



## 判词档位设计（最终版，2026-08-15）

> 产品 12 规则→4 档 · 供应商 6 规则→4 档 · 综合 9 档。改判词逻辑前先看这里。代码权威源：domain/evaluate/_product.py、_supplier.py、evaluator.py。

0. 先看子维度（判断的原料）
产品 6 维，每个判断啥、怎么分档：

子维度	判断的是啥	强(3)	中(2)	弱(1)
D1 销量	卖得动吗	>1000	100~1000	<100
D2 复购	买过的还回来吗	>30%	10~30%	≤10%
D3 门槛	试单成本低吗	价<20 且 起订≤10	价<50 且 起订≤100	其他
D4 好评	口碑好吗	≥98%	≥95%	<95%
D5 关注	多少人想买	>100	30~100	≤30
D6 退货	有7天无理由吗	有	—	无
供应商 3 维：

子维度	判断的是啥	强	中	弱
身份	是不是真工厂	超级工厂/旗舰/实力	自称工厂	贸易商
认证	第三方验过吗	深度验厂/SGS/TUV	基础认证	无
年限	开了几年	≥3年	1~3年	<1年
1. 产品 12 个结果 → 给 AI
#	结果	判定条件（用哪些子维度）	给 AI 的 tier	AI 据此的语气(tone)
1	出手·复购好	D2复购强 + D1销量中上	go_repurchase	positive 积极
2	出手·卖爆+关注高	D1销量强 + D5关注强	go_hot_wanted	positive
3	出手·卖爆+有复购	D1销量强 + D2复购中上	go_hot_repeat	positive
4	试·卖爆但啥未知	D1销量强 + D2无 + D5不高	trial_hot_unknown	positive→偏谨慎
5	试·关注高没卖起来	D5关注强 + D1销量弱	trial_wanted_low	positive→偏谨慎
6	试·复购好没量+门槛低	D2复购强 + D1销量弱 + D3门槛中上	trial_rep_low	positive→偏谨慎
7	试·3个中等	任意3维=中	trial_medium3	positive→偏谨慎
8	警·卖爆没人回头	D1销量强 + D2复购弱	caution_hot_low	cautious 提醒
9	警·复购好没量+门槛高	D2复购强 + D1销量弱 + D3门槛低	caution_rep_low	cautious
10	观·1-2个中等	任意1-2维=中	watch_medium12	neutral 中性
11	观·全平平	其余全掉这	watch_flat	neutral
12	跳过·数据不足	销量+复购+退货 缺≥2	skip	neutral
外加「致命·好评<80%」→ tier=fatal_badrate，tone=negative 否定。

2. 供应商 6 规则 → 5 tier → 4 档 → 给 AI
#	结果	判定条件	给 AI 的 tier	tone
1	信任	身份强 + 认证强	trust_strong2	(配合产品定)
2	还行	强-弱净分 ≥ 1	usable_ok	—
3	警惕	身份弱（贸易商）一票警惕，或其余	caution_weak2	—
4	致命	身份+认证+年限全空	fatal_blackbox	negative
5	跳过	身份+年限 缺≥2	skip	neutral
3. 综合 9 个 → 给 AI
#	结果	判定条件（产品档 × 供应商档）	给 AI 的 tier
1	出手	产品go + 供应商信任	go_both
2	出手(产品为主)	产品go + 供应商还行	go_product_ok
3	有条件(供应商弱)	产品go + 供应商警惕	conditional_supplier_weak
4	有条件(工厂强)	产品试/警 + 供应商信任	conditional_factory_strong
5	有条件(还行)	产品试/警 + 供应商还行	conditional_ok
6	有条件(谨慎)	产品试/警 + 供应商警惕	conditional_careful
7	不碰(供应商致命)	供应商致命	no_supplier_fatal
8	不碰(产品致命)	产品致命	no_product_fatal
9	等数据	数据不足	wait_data
4. 每个结果额外还喂给 AI 什么（都一样，不分结果）
除了上面的 tier，pack_ai_input 还给 AI 塞这些共享内容：

字段	是啥	作用
must_mention	销量 X 件、复购 Y%、价格/MOQ、好评、关注、退货警告	AI 写判词必须提到这些数字
must_not_say	按 tier 生成的禁词（如 fatal 禁"值得买"、watch 禁"爆款"）	AI 禁止说，防止越档乱夸
action	一句话行动（拿样/算成本/等数据/跳过）	AI 写"下一步该干啥"
context	试错成本（¥最低下单额）、供应商摘要	AI 写话的参考背景
dimensions	6+3 维的 signal(正/中/负)+label+数据	AI 校验数字用

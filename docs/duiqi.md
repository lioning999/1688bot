用户输入 1688 链接 + 选语言（如 en）
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 节点 1 — routes/analyze.py  POST /api/analyze               │
│                                                             │
│ 做什么：                                                     │
│   1. 校验 URL 是 1688 链接                                   │
│   2. 提取 offer_id                                           │
│   3. 全局限流检查（rate_limiter.py）                          │
│   4. 用户配额检查（user_repo.py → 查 quota 字段 + 懒重置）     │
│                                                             │
│ 返回：{ task_id, status: "pending" }  ← 立即返回，不等结果    │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 节点 2 — services/analyze_svc.py  AnalyzeService.start()    │
│                                                             │
│ 做什么：                                                     │
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
│ 返回：task_id                                                │
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
│   │ SQL: SELECT raw_json, display_i18n                   │   │
│   │      FROM analysis                                  │   │
│   │      WHERE offer_id=? AND user_id=? AND status='done'│   │
│   │                                                     │   │
│   │ 三级判断：                                            │   │
│   │ ① 没查到 → 走 3.2 Apify 抓取                          │   │
│   │ ② 查到 raw_json + display_i18n 有当前语言              │   │
│   │    → 直接返回display_i18n，0 次 AI。
           跳过 Apify + mapper + judge    │   │
│   │    → 原因：同用户同商品同语言，上次已翻好，没必要重跑   │   │
│   │ ③ 查到 raw_json 但 display_i18n 没有当前语言           │   │
│   │    → 跳过 Apify，走 3.3 mapper+judge+翻译              │   │
│   │    → 原因：语言不同，需要从 raw_json 重建 + 追加翻译    │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
│ 子节点 3.2 — Apify 抓取（仅 DB 无 raw_json 时）              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 文件：adapters/apify_adapter.py                      │   │
│   │ 方法：fetch_product_by_url(1688链接)                  │   │
│   │                                                     │   │
│   │ 输入：1688 商品链接                                   │   │
│   │ 输出：原始 raw_json（标题/价格/图片/供应商/规格/SKU/销量）  │   │
│   │ 超时：90 秒                                          │   │
│   │ 失败 → 退配额 + 记录失败次数                          │   │
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
│ 子节点 3.4 — 规则引擎打分 + 判词（不产文案，只出 KEY）      │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 文件：domain/verdict_engine.py                        │   │
│   │ 方法：judge_all(mapped)                               │   │
│   │                                                     │   │
│   │ 输入：3.3 mapper 产出的 mapped dict（~50字段）         │   │
│   │                                                     │   │
│   │ 做什么：根据 mapped 数据做判断，产出 3 个判词 KEY        │   │
│   │   ① 产品判词：认证 + 销量 + 7天退货 → 4档               │   │
│   │   ② 工厂判词：身份 + 认证 + 年限 → 5档                  │   │
│   │   ③ 拿样判词：固定（两段付款）                          │   │
│   │                                                     │   │
│   │ 输出：3 个 KEY + 参数                                  │   │
│   │   {"product": {key:"verdict_product_recommend",        │   │
│   │                params:{price:"5",moq:"1",unit:"件"}},  │   │
│   │    "factory": {key:"verdict_factory_reliable",         │   │
│   │                params:{years:"5",cert:"SGS"}},         │   │
│   │    "sample":  {key:"verdict_sample_two_payment"}}      │   │
│   │                                                     │   │
│   │ 然后塞进 mapped dict，一起传给 3.5：                    │   │
│   │   mapped["verdict_product"] = verdicts["product"]      │   │
│   │   mapped["verdict_factory"] = verdicts["factory"]      │   │
│   │   mapped["verdict_sample"]  = verdicts["sample"]       │   │
│   │                                                     │   │
│   │ 最终文案由 3.5 builder.py 查 glossary.json 填入参数，   │   │
│   │ 5 语言预翻译，不调 AI                                   │   │
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
│   │              specs, sales, priceTiers, verdictProduct, │   │
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


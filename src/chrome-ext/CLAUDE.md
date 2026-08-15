# Chrome Extension 前端框架护栏
> Layer 2 — MV3 标准架构约束。改插件代码前必读。
> 最后更新：2026-08-09

---

## 一、MV3 架构铁律

```
Side Panel (HTML/CSS/JS)     Service Worker (JS)        FastAPI 后端
┌──────────────────────┐     ┌──────────────────┐     ┌──────────────┐
│ sidepanel.html        │     │ service-worker.js │     │ src/api/     │
│ sidepanel.js  (纯UI)  │────▶│ (唯一网络出口)     │────▶│ routes/      │
│ history.js    (纯UI)  │     │                  │     │ services/    │
│ lib/api.js   (通道)   │     │ Token 管理        │     │              │
│ lib/i18n.js  (翻译)   │     │ Badge 状态        │     │              │
└──────────────────────┘     └──────────────────┘     └──────────────┘
```

| 规则 | 说明 |
|------|------|
| **Side Panel 禁止 `fetch()`** | 所有网络请求通过 `API.xxx()` → `chrome.runtime.sendMessage` → SW |
| **SW 是唯一网络出口** | `host_permissions` 在 manifest.json 声明，SW 内 fetch 不受 CORS 限制 |
| **登录必须走 SW** | `chrome.identity.launchWebAuthFlow` 只在 SW context 可用 |
| **Token 存在 `chrome.storage.local`** | SW 自主读取，不信任 side panel 传参 |
| **动态 ext_id** | `chrome.runtime.id` 传给后端，不用 manifest 写死的 ID |

---

## 二、数据流 & display JSON 契约

### 管线

```
1688 URL → API.analyze(url, lang) → SW: POST /api/analyze
  → 后端 analyze_svc._run()
    → Apify 抓取 → map_raw() → judge_all()
    → build_result_with_display(mapped, offer_id, lang)
      ├─ lang=zh: build_display(mapped) → 模板路径
      └─ lang=en/vi/th: build_with_ai(mapped, lang) → Qwen AI 路径
  → display JSON → SW → sidepanel.js: render()
```

### display JSON 字段映射表

> **权威源：** `src/api/domain/display/builder.py` 的 `_EXPECTED_KEYS` + 各 `_build_*` 函数输出。
> **铁律：改 display 字段名必须先更新此表，再改前后端。**

#### 顶层 & p01 产品确认

| display 路径 | 类型 | 前端取值 | 数据来源 |
|-------------|------|---------|---------|
| `title` | string | `display.title` | mapper / AI 翻译 |
| `images[0]` | string(URL) | `display.images[0]` | Apify 原始 |
| `price.low` | number | `display.price.low` | mapper |
| `price.high` | number | `display.price.high` | mapper |
| `price.moq` | number | `display.price.moq` | mapper |
| `price.unit` | string | `display.price.unit` | glossary(unit_{unit}, lang) |
| `sales.sold` | string | `display.sales.sold` | glossary(sales_sold_fmt, lang) |
| `trustBar.label` | string | `display.trustBar.label` | glossary(raw_label, lang) |
| `factory.rankText` | string | `display.factory.rankText` | mapper → 加 emoji 前缀 |

#### ② 综合结论 summaryLine

| display 路径 | 类型 | 前端取值 | 数据来源 |
|-------------|------|---------|---------|
| `summaryLine.headline` | string | 直接取 `s.headline` | glossary(verdict key, lang) |
| `summaryLine.reason` | string | 直接取 `s.reason` | glossary 或 Qwen AI |
| `summaryLine.verdict` | string | 直接取 `s.verdict` | glossary(verdict key, lang) |

#### ③ 产品验证 productEval

| display 路径 | 类型 | 前端取值 | 数据来源 |
|-------------|------|---------|---------|
| `productEval.score` | number | `pe.score` | evaluate_product() |
| `productEval.max_score` | number(18) | `pe.max_score` | 固定值 |
| `productEval.grade` | "go"\|"ok"\|"bad"\|"none" | `pe.grade` | evaluate_product() |
| `productEval.summary` | string | `pe.summary` | glossary(prod_summary_*, lang) |
| `productEval.verdict` | string | `pe.verdict` | glossary(prod_verdict_*, lang) 或 Qwen AI |
| `productEval.stockLevel` | {level, text} | `pe.stockLevel.text` | mapper.stock → glossary |
| `productEval.dimensions[]` | array | 遍历渲染 | evaluate_product() × glossary |

#### ④ 供应商验证 supplierEval

| display 路径 | 类型 | 前端取值 | 数据来源 |
|-------------|------|---------|---------|
| `supplierEval.score` | number | `se.score` | evaluate_supplier() |
| `supplierEval.max_score` | number(9) | `se.max_score` | 固定值 |
| `supplierEval.grade` | "go"\|"ok"\|"bad"\|"none" | `se.grade` | evaluate_supplier() |
| `supplierEval.summary` | string | `se.summary` | glossary(supp_summary_*, lang) |
| `supplierEval.verdict` | string | `se.verdict` | glossary(supp_verdict_*, lang) 或 Qwen AI |
| `supplierEval.companyName` | string | `se.companyName` | mapper.supplierName |
| `supplierEval.industryCluster` | string | `se.industryCluster` | glossary(explain_industry_fmt, lang) |
| `supplierEval.dimensions[]` | array | 遍历渲染 | evaluate_supplier() × glossary |

#### dimensions[] 通用结构

| 字段 | 类型 | 前端取值 | 说明 |
|------|------|---------|------|
| `key` | string | `d.key` | 维度标识 d1-d6 / s1-s3 |
| `score` | number | `d.score` | 该维度得分 |
| `icon` | string | `d.icon` | emoji 图标 |
| `name` | string | `d.name` | 已翻译的维度名 |
| `label` | string | `d.label` | 可用作组头标签 |
| `data` | string | `d.data` ← **这是 `data`，不是 `data_text`！** | 已翻译的数据列 |
| `ref` | string | `d.ref` ← **这是 `ref`，不是 `benchmark_text`！** | 已翻译的标杆/参考值 |
| `na` | boolean | `d.na` | 无数据标记 |

#### ⚠️ 常见字段名错误（禁止）

| ❌ 错误写法 | ✅ 正确写法 | 出过 bug |
|------------|-----------|---------|
| `d.data_text` | `d.data` | ✅ 修过 |
| `d.data_key` | `d.key` | — |
| `d.data_num` | 后端不发此字段 | — |
| `d.benchmark_text` | `d.ref` | ✅ 修过 |
| `d.benchmark_key` | 后端不发此字段 | — |
| `d.benchmark_num` | 后端不发此字段 | — |
| `d.name_key` | `d.name`（已翻译） | — |

---

## 三、数据权威源声明

| 数据层级 | 权威源 | 信任度 |
|---------|-------|:--:|
| 结构化数字（价格/销量/MOQ/年限） | `dimensions[].data` — glossary 模板 + mapper 数值 | ⭐⭐⭐ 确定 |
| 规则判词（产品/供应商 verdict） | `productEval.verdict` — glossary 模板 + 规则引擎参数 | ⭐⭐⭐ 确定 |
| AI 判词（en/vi/th verdict） | `productEval.verdict` — Qwen 生成（`_aiGenerated` 标记） | ⭐⭐ 可能含幻觉 |
| 库存/排名/公司/产业带 | 各自的 display 字段 — mapper 原始值 | ⭐⭐⭐ 确定 |

> **铁律：渲染数字永远用 `dimensions[].data`，禁止从 `verdict` 文本中提取数字。**
> Qwen 生成的 verdict 文本中的数字（如 "复购率 49.8%"）可能与 dimensions 真实数据不一致。

---

## 四、状态管理铁律

### 全局状态变量

| 变量 | 用途 | 何时清除 |
|------|------|---------|
| `_currentOfferId` | 当前渲染报告的 offerId | 用户点「生成报告」分析新产品 / 退出登录 |
| `_activeTaskId` | 正在轮询的 taskId | 任务完成 / 失败 / 超时 / 页面离开 |
| `_searching` | 分析进行中防重 | `resetSearchBtn()` / 失败路径 |
| `_pollTimer` | 轮询定时器引用 | `stopPolling()` / `beforeunload` |
| `_currentPriceLow` | 当前产品最低价 | 新报告渲染时覆盖 |
| `_currentMoq` | 当前产品起订量 | 新报告渲染时覆盖 |

### 铁律

1. **`beforeunload` 必须清理 `_pollTimer`** — 页面关闭时 clearTimeout
2. **`_searching` 防重** — 所有分析入口必须 `if (_searching) return;`
3. **轮询上限** — 最多 60 次（2 分钟），超时显示错误
4. **Tab 切换不丢报告** — `_currentOfferId` 有值时，`processUrl()` 不重置状态；检测到不同 1688 商品时显示检测条
5. **退出登录清除一切** — `_currentOfferId = null` + `hideDetectBar()` + `showEmpty('notLoggedIn')`

---

## 五、翻译分层（三层，职责分明）

```
┌─────────────────────────────────────────────────────────┐
│ ① 前端 i18n — 只翻译「壳」                               │
│    lang/{zh,en,vi,th}.json                              │
│    按钮文案、标签、提示、固定 UI 文本                      │
│    I18N.t(key) → 每种商品一样，与数据无关                  │
├─────────────────────────────────────────────────────────┤
│ ② 后端 glossary.json — 判词 + 术语（预翻译，静态）        │
│    src/api/domain/data/glossary.json                     │
│    规则判词、维度名、标杆文案、卖家标签、库存档位           │
│    builder.py: _glossary(key, lang) → 5 语言平行翻译      │
│    中文由我们产出、可穷举 → 不调 AI                        │
├─────────────────────────────────────────────────────────┤
│ ③ Qwen AI 判词 — 判词语优化 + 标题/供应商名翻译            │
│    services/ai_verdict_svc.py → build_with_ai()            │
│    母语 system prompt（domain/display/verdict_prompts.json）│
│    一次 Qwen 调用输出：判词(3字段) + 标题翻译 + 供应商名     │
│    仅 lang=en/vi/th 时触发，zh 走 glossary 模板             │
└─────────────────────────────────────────────────────────┘
```

| 层 | 管什么 | 不管什么 |
|----|-------|---------|
| ① 前端 i18n | 页面框架文案（按钮/标签/提示/空态） | 商品数据、判词内容 |
| ② glossary | 规则判词、维度名、行业术语、档位标签 | 1688 动态中文原文 |
| ③ Qwen AI | 1688 商品标题、规格参数、动态描述 | UI 壳文案、静态判词模板 |

> **铁律：新增翻译 → 先判断归属层。层①加 i18n JSON，层②加 glossary.json，只有来自 1688 的动态中文才走层③。**

### i18n 操作规范

- 新增 UI 文案 → 4 语言 JSON 同步追加，key 前缀 `inspect.` / `plugin.` / `report.` / `history.`
- `zh.json` 是源语言，其他语言的 key 必须与 zh.json 完全一致
- `I18N.t(key)` 找不到时返回 `key` 自身（降级显示）

---

## 六、XSS & 安全底线

- **所有后端/URL/用户输入的数据插入 HTML 前必须过 `escHtml()`**
- **禁止 HTML 内联 `onclick=`** → 统一 `addEventListener`
- **Token 不进入日志** — console.log 禁止打印 token 内容
- **`innerHTML` 赋值前必须确认内容已转义**

---

## 七、文件结构

```
src/chrome-ext/
├── manifest.json         # MV3, host_permissions, side_panel
├── service-worker.js     # 唯一网络出口 + Token + Badge
├── sidepanel.html        # 分析报告页 DOM
├── sidepanel.js          # 报告页渲染 + 交互 + 状态管理
├── sidepanel.css         # 样式（对齐 web/inspect.css design tokens）
├── history.js            # 历史记录页（独立模块，window.HistoryPage）
├── lib/
│   ├── api.js            # Promise 消息通道（API.xxx() → SW）
│   └── i18n.js           # 多语言加载 + I18N.t()
└── lang/
    ├── zh.json           # 中文（源语言）
    ├── en.json
    ├── vi.json
    └── th.json
```

## 八、禁止事项

| 禁止 | 原因 |
|------|------|
| ❌ side panel 直接 `fetch()` | 必须走 SW 消息通道 |
| ❌ 凭训练数据推测 display 字段名 | 对照本文 §二 映射表 |
| ❌ `innerHTML` 不经 `escHtml()` | XSS |
| ❌ HTML 内联 `onclick=` | 统一 `addEventListener` |
| ❌ 未清理的 `setTimeout`/`setInterval` | beforeunload 清理 |
| ❌ 手写 toast HTML | 用 `showToast()` |
| ❌ console.log 打印 token | 安全 |
| ❌ 从 verdict 文本提取数字渲染 | 用 dimensions[].data |

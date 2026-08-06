# 开发计划 — AI 判词

> 创建：2026-08-06 | 状态：待开发 | 工期：3.5 天 | 破坏面：0

---

## 一、背景

### 1.1 为什么做

当前判词用 glossary 模板拼接（如 `"值得做。卖得火（{sold}件）+ 当前热度高（{wanted}人想看）"`）。僵硬、翻译腔、无法适配不同市场的表达习惯。

### 1.2 目标

规则引擎定 tier（100% 准确），一次 Qwen 调用同时出判词+翻译，逐字段校验，单个字段失败只降级该字段。

### 1.3 不改的

- 评估引擎（`evaluator.py`、`_evaluator_*.py`）
- 产品映射（`product_mapper.py`）
- 前端（`inspect.html`、`inspect.js`）
- 数据库
- `config.py`

---

## 二、技术架构

### 2.1 核心思路

```
规则引擎(tier) → 打包结构化数据 → 一次Qwen → 逐字段校验 → display JSON
                  ↑ 结论+论据+禁区+行动+翻译
```

**行业对标：** GitHub Copilot Code Review（规则扫 issues → LLM 写 comment）、Notion AI（结构化→摘要）。行业标准做法。

### 2.2 数据流

```
改前：map_raw → judge_all → build_display → translate_display → 前端
                            ↑ 模板拼判词    ↑ Qwen翻译1688原文

改后：map_raw → build_display → _build_with_ai → 前端
                    ↑ 模板兜底   ↑ 一次Qwen: 判词+翻译
                                  ↑ translator检测_aiGenerated跳过
```

### 2.3 分层严格遵守

| 层 | 放什么 | 不放什么 |
|------|------|------|
| **domain/** | `pack_ai_input()`、`validate_ai_output()` — 纯函数 | ❌ 不调 Qwen、不读环境变量 |
| **domain/** | `verdict_prompts.json` — prompt 模板 | — |
| **services/** | `_build_with_ai()`、`_merge_ai_verdicts()` — 编排+调 Qwen | ❌ 不写 prompt 逻辑 |
| **adapters/** | `qwen_adapter.chat()` — HTTP 调用（复用，不动） | — |

---

## 三、文件改动清单

### 3.1 新建文件

| 文件 | 行数 | 内容 |
|------|:--:|------|
| `domain/verdict_prompts.json` | ~80 | system prompt + 输出 JSON schema + 4 语言市场适配文案 |

### 3.2 修改文件

| # | 文件 | 函数 | 动作 | 行数 |
|:--:|------|------|------|:--:|
| 1 | `domain/display_builder.py` | `pack_ai_input()` | **新建** — 评估结果 + mapped → AI 输入 JSON | +60 |
| 2 | `domain/display_builder.py` | `validate_ai_output()` | **新建** — 硬约束精确匹配 + 软约束语义检查 + tier 不走样 | +50 |
| 3 | `services/analyze_svc.py` | `_build_with_ai()` | **新建** — 编排：评估→打包→调Qwen→校验→替换 | +60 |
| 4 | `services/analyze_svc.py` | `_merge_ai_verdicts()` | **新建** — 逐字段独立降级 | +30 |
| 5 | `services/analyze_svc.py` | `build_result_with_display()` | **修改** — lang≠zh 时走 `_build_with_ai` | ±10 |
| 6 | `domain/translator.py` | `translate_display()` | **修改** — 检测 `_aiGenerated` 标记则跳过 | +5 |

**总计：+210 新行，±15 改行。0 文件删除。**

---

## 四、前置准备（开发前必须就绪）

### 4.1 测试数据

| 数据 | 路径 | 状态 |
|------|------|:--:|
| 连衣裙 Apify 原始数据 | `tests/data/894464302316_raw.json` | ✅ 已有 |
| 转转马 Apify 原始数据 | `src/web/samples/muhezi/data.json` | ✅ 已有 |
| 太阳镜 Apify 原始数据 | `tests/data/723736665098_raw.json` | ✅ 已有 |
| 唇釉 Apify 原始数据 | `tests/data/1072003774933_raw.json` | ✅ 已有 |
| 手表 Apify 原始数据 | `tests/data/1062465593257_raw.json` | ✅ 已有 |

### 4.2 硬约束字段清单（价格等必须精确匹配）

```python
HARD_CONSTRAINTS = [
    "price",       # ¥69.00 必须原样
    "moq",         # 1件 必须原样
    "return7day",  # 支持/不支持 不可模糊
    "cert_type",   # TUV/SGS/intertek 必须原样
]
```

### 4.3 软约束字段清单（可以有本地化表达但不能遗漏）

```python
SOFT_CONSTRAINTS = [
    "sold_count",      # 5142 → 可为 "5.142 đơn" 或 "hơn 5.000 đơn"
    "wantBuy_count",   # 3436 → 同上
    "repurchase_rate", # 68% → 必须出现数字
    "supplier_identity", # 工厂/贸易商 → 不可反着说
    "shop_years",      # 2年 → 必须出现
]
```

### 4.4 Tier 关键词对照表（validate_tier 用）

| Tier | 判词中必须含的关键词（任一） | 判词中禁止含的关键词 |
|------|------|------|
| `go_*` | 值得做、可以出手、推荐 | 谨慎、不建议、观望、跳过 |
| `trial_*` | 值得试、试试、小批量 | 不建议、跳过、放心批量 |
| `caution_*` | 谨慎、注意、先算账 | 放心、推荐、强烈建议 |
| `watch_*` | 观望、等一等、先收藏 | 值得做、可以出手 |
| `fatal_*` | 不建议、别碰、换品 | 值得试、推荐 |
| `skip` | 数据不够、判断不了、等数据 | 可以做、值得做 |

### 4.5 4 语言市场适配文案（prompt 中注入）

| 语言 | 市场 | 适配文案（示例） |
|------|------|------|
| vi | 越南 Shopee | "Shopee VN rất nhạy với đánh giá thấp — xác nhận chính sách đổi trả trước khi đặt hàng" |
| th | 泰国 Lazada | "Lazada TH คืนสินค้าเข้มงวด — ตรวจสอบตัวอย่างก่อนสั่งจำนวนมาก" |
| id | 印尼 TikTok | "TikTok Shop bisa viral cepat — pastikan stok pabrik cukup sebelum push" |
| en | 通用 | "Verify sample quality before bulk ordering" |

---

## 五、Phase 1（第 1 天）— 纯函数 + Prompt

### 任务 1.1：`verdict_prompts.json`

**文件：** `domain/verdict_prompts.json`（新建）

**结构：**
```json
{
  "system": {
    "role": "Bạn là trợ lý thu mua 1688...",
    "output_format": {
      "product_verdict": "string — đánh giá sản phẩm...",
      "supplier_verdict": "string — đánh giá nhà cung cấp...",
      "summary_verdict": "string — kết luận tổng hợp...",
      "translated_title": "string — tiêu đề đã dịch...",
      "translated_supplier_name": "string — tên NCC đã dịch..."
    },
    "rules": [
      "Tuyệt đối không thay đổi số liệu gốc",
      "Phải đề cập đến tất cả các điểm trong must_mention",
      "Không được nói những điều trong must_not_say",
      "..."
    ]
  },
  "market_notes": {
    "vi": "Shopee VN rất nhạy với đánh giá thấp...",
    "th": "Lazada TH คืนสินค้าเข้มงวด...",
    "id": "TikTok Shop bisa viral cepat...",
    "en": "Verify sample quality before bulk ordering"
  }
}
```

**验收标准：** 4 语言各一份 system prompt，输出 JSON schema 明确。

### 任务 1.2：`pack_ai_input()`

**文件：** `domain/display_builder.py`（追加）

**函数签名：**
```python
def pack_ai_input(
    product_raw: dict[str, Any],
    supplier_raw: dict[str, Any],
    summary_raw: dict[str, Any],
    mapped: dict[str, Any],
    lang: str,
) -> dict[str, Any]:
```

**输出 JSON 结构：**
```json
{
  "conclusion": {
    "product_tier": "go_hot_wanted",
    "supplier_tier": "caution_weak2",
    "summary_tier": "conditional_supplier_weak",
    "headline": "Sản phẩm tốt nhưng nhà cung cấp yếu",
    "tone": "positive_but_cautious"
  },
  "must_mention": [
    "doanh số 5,142 đơn (chuẩn >1,000)",
    "3,436 người muốn mua (chuẩn >100)",
    "thương lái, không phải xưởng",
    "không có chứng nhận bên thứ ba",
    "giá 4.50 tệ, moq 1"
  ],
  "must_not_say": [
    "nhà máy đáng tin cậy",
    "yên tâm đặt hàng"
  ],
  "action": "Lấy 2-3 mẫu kiểm tra chất lượng, chụp ảnh xác nhận rồi hãy đặt hàng loạt",
  "context": {
    "trial_cost": "cực thấp — 4.50 tệ",
    "supplier_summary": "thương lái Nghĩa Ô, 2 năm, không chứng nhận",
    "market_note": "Shopee VN rất nhạy với đánh giá xấu..."
  },
  "dimensions": {
    "product": [
      {"signal": "positive", "label_vi": "Doanh số", "data_vi": "5,142 đơn", "ref_vi": ">1,000"},
      {"signal": "neutral", "label_vi": "Mua lại", "data_vi": "không có dữ liệu"},
      ...
    ],
    "supplier": [
      {"signal": "negative", "label_vi": "Thân phận", "data_vi": "thương lái"},
      ...
    ]
  },
  "to_translate": {
    "title": "景德镇陶瓷转转小马旋转马有钱小摆件...",
    "supplier_name": "义乌市锂迪电子商务商行（个体工商户）"
  }
}
```

**验收标准：** 5 case 输入 → 输出合法 JSON → 人工检查 must_mention 完整 / must_not_say 正确 / dimensions 信号方向正确。

### 任务 1.3：`validate_ai_output()`

**文件：** `domain/display_builder.py`（追加）

**函数签名：**
```python
def validate_ai_output(
    ai_text: str,
    must_mention: list[str],
    ai_input: dict[str, Any],
) -> bool:
```

**校验规则：**

| 优先级 | 校验项 | 方式 | 失败处理 |
|:--:|------|------|------|
| 1 | 硬约束字段精确存在 | 价格/MOQ/退货状态/cert 类型 regex | 该字段降级模板 |
| 2 | 软约束字段语义存在 | 销量/关注/复购率 数字或近似表达 | 该字段降级模板 |
| 3 | tier 不走样 | 判词含 tier 对应关键词、不含禁止词 | 该字段降级模板 |
| 4 | must_mention 全部命中 | 逐个 grep | 该字段降级模板 |

**验收标准：** 
- 输入正确判词 → 返回 True
- 输入漏了 must_mention 的判词 → 返回 False
- 输入改了数字的判词（5142→5000）→ 返回 False
- 输入 tier 走样的判词（go→"谨慎"）→ 返回 False

### 任务 1.4：Phase 1 独立测试

**测试脚本：** `tests/test_ai_pipeline_phase1.py`

**测试内容：**
1. 5 case × pack_ai_input → 输出 JSON 结构验证
2. 手写 5 个"正确判词" → validate 返回 True
3. 手写 5 个"有问题判词"（漏 must_mention / 改数字 / tier 走样）→ validate 返回 False
4. 5 case 的 pack 输出 → 人工检查 prompt 质量（不调 Qwen）

---

## 六、Phase 2（第 1.5-2.5 天）— 编排 + Prompt 调优

### 任务 2.1：`_build_with_ai()`

**文件：** `services/analyze_svc.py`（追加）

**函数签名：**
```python
async def _build_with_ai(
    mapped: dict[str, Any],
    lang: str,
) -> dict[str, Any]:
```

**流程：**
```
① evaluate_product / evaluate_supplier / evaluate_summary
② build_display(mapped, lang) → 模板兜底
③ if lang == "zh": return display
④ pack_ai_input(...) → ai_input
⑤ qwen_adapter.chat(system=prompt, user=json.dumps(ai_input), timeout=8.0)
⑥ json.loads(response) → ai
⑦ _merge_ai_verdicts(display, ai, ai_input)
⑧ display["_aiGenerated"] = lang
⑨ return display
```

**异常处理：**
- Qwen 超时 → 返回模板 display（已有）
- Qwen 返回非 JSON → 返回模板 display
- json.loads 失败 → 返回模板 display
- 任何异常 → 返回模板 display

### 任务 2.2：`_merge_ai_verdicts()`

**文件：** `services/analyze_svc.py`（追加）

**函数签名：**
```python
def _merge_ai_verdicts(
    display: dict[str, Any],
    ai: dict[str, Any],
    ai_input: dict[str, Any],
) -> dict[str, Any]:
```

**替换映射表：**
```python
FIELD_MAP = [
    # (display_path, ai_key, must_mention_key)
    ("productEval", "verdict", "product_verdict", "must_mention"),
    ("supplierEval", "verdict", "supplier_verdict", "supplier_must_mention"),
    ("summaryLine", "reason", "summary_verdict", None),
    (None, "title", "translated_title", None),             # 顶层字段
    ("factory", "supplierName", "translated_supplier_name", None),
]
```

每个字段独立：`if ai_key存在 and validate通过 → 替换 display[path][field]`，否则保留模板值。

### 任务 2.3：`build_result_with_display()` 分支

**文件：** `services/analyze_svc.py`（修改）

**现状：**
```python
display = build_display(mapped, lang)
if lang != "zh":
    display = await translate_display(display, lang)
```

**改为：**
```python
if lang != "zh":
    display = await _build_with_ai(mapped, lang)
else:
    display = build_display(mapped, lang)
```

### 任务 2.4：translator 跳过逻辑

**文件：** `domain/translator.py`（修改）

**现状：** `translate_display(display, lang)` → 翻译所有 Path 3 字段

**改为：** 函数开头加：
```python
if display.get("_aiGenerated"):
    return display  # AI 已经处理过翻译，跳过
```

### 任务 2.5：Prompt 调优

**流程：**
1. 跑 5 case × 4 语言（vi/th/id/en）= 20 个输出
2. 人工检查每个输出
3. 统计：
   - validate 通过率（预期 >80%）
   - 判词质量（人工评分 1-5）
   - 常见问题归类
4. 修 prompt → 重跑 → 再检查
5. 目标：validate 通过率 >90%、判词质量 >4 分

---

## 七、Phase 3（第 3-3.5 天）— 兜底验证

### 任务 3.1：异常场景

| 场景 | 模拟方式 | 预期结果 |
|------|------|------|
| Qwen 超时 | timeout=0.001s | 返回模板 display |
| Qwen 返回非 JSON | mock 返回纯文本 | 返回模板 display |
| AI 漏 must_mention | prompt 里要求少写一条 | 该字段模板兜底，其他字段 AI |
| AI 改数字 | prompt 里要求四舍五入 | validate 失败，该字段模板兜底 |
| 所有字段校验失败 | mock 全部空 | 全量模板，体验与现在一致 |

### 任务 3.2：zh 路径零影响

- zh lang → 不走 `_build_with_ai` → 直接 `build_display`
- 中文用户看到的体验与现在完全一致
- translator 也跳过（zh 本来就不翻译）

### 任务 3.3：前端回归

- 5 case × zh + 4 语言各至少 1 个 = 9 个页面
- 确认：颜色 ✅、维度 ✅、标题 ✅、供应商名 ✅、判词 ✅
- 确认 _aiGenerated 标记不会泄漏到前端

### 任务 3.4：性能验证

- 一次完整分析（Apify + AI）：总延迟 <75s
- AI 部分延迟：<5s
- 模板兜底路径延迟：与现在一致

---

## 八、验收标准

| # | 标准 | 量化 |
|:--:|------|:--:|
| 1 | AI 判词 validate 通过率 | >90%（20 个输出中 ≥18 个通过） |
| 2 | 降级不崩溃 | 5 种异常场景全通过 |
| 3 | zh 路径不受影响 | 3 case 输出与改前一模一样 |
| 4 | 前端无改动 | display JSON 结构不变，前端 9 页面正常渲染 |
| 5 | 数字不篡改 | 20 个输出中 0 个数字被改 |
| 6 | tier 不走样 | 20 个输出中 0 个 tier 颜色被改 |
| 7 | 性能不退化 | 模板兜底路径延迟 ≤ 改前 + 0.1s |

---

## 九、风险汇总

| # | 风险 | 等级 | 概率 | 应对 |
|:--:|------|:--:|:--:|------|
| 1 | AI JSON 不稳定 | ⚠️ 中 | 5% | json.loads 失败 → 模板兜底 |
| 2 | AI 漏关键信息 | ⚠️ 中 | 15% | 逐字段校验 → 独立降级 |
| 3 | AI 篡改数字 | 🔴 高 | 10% | 硬约束精确匹配，改了就降级 |
| 4 | Prompt 注入 | 🔴 高 | 3% | 1688 数据走 JSON，不拼自然语言 |
| 5 | Qwen 不可用 | 🟡 低 | 3% | 全量模板兜底 = 现在体验 |
| 6 | 多语言 prompt 质量不均 | ⚠️ 中 | 20% | Phase 2 逐语言检查，调优 |
| 7 | 越南语数字格式冲突 | 🟡 低 | 10% | 软约束不要求精确格式 |

# 技术方案 — AI 判词

> 最后更新：2026-08-06 | 状态：方案已定，待开发

---

## 一、现状（4 步）

```
① map_raw()           → 标准化数据
② judge_all()         → 旧判词（已废弃不用，代码还在）
③ build_display()     → 评估 + glossary 模板拼判词
④ translate_display() → Qwen 翻译标题 / 供应商名
⑤ 前端
```

## 二、改后（4 步）

```
① map_raw()           → 标准化数据（不变）
② build_display()     → 评估 + glossary 模板拼判词（不变，作为 AI 挂了时的兜底）
③ _build_with_ai()    → 【新加的】一次 Qwen 调出判词 + 翻译，替换 ② 的模板结果
④ 前端
   ↑ translate_display() 检测到 ③ 已翻译，跳过（加 5 行）
```

**变化就两件事：**

| 动作 | 文件 | 改什么 |
|------|------|------|
| 加一个函数 | `services/analyze_svc.py` | `_build_with_ai()` — 调一次 Qwen，同时出判词+翻译 |
| 改一个函数 | `domain/translator.py` | `translate_display()` — 加 5 行，检测到标记就跳过 |

**AI 挂了怎么办：** 用户的体验和现在一模一样。② 的模板判词兜底，④ 继续翻译标题。

---

## 三、方案

### 核心思路

规则引擎定 tier（100% 准确） → 打包结构化数据（结论 + 论据 + 禁区 + 行动 + 市场适配 + 需翻译原文）→ **一次 Qwen 调用** → 逐字段校验 → 写入 display JSON。

### 改动总览

```
                                    【新建】
analyze_svc.py               domain/verdict_prompts.json
  ├─ build_result_with_display()     AI prompt 模板
  │    └─ 调 _build_with_ai()  ←────【新建函数，service 层】
  │         ├─ evaluate_*()           domain — 纯函数（内部自调，不从 build_display 传参）
  │         ├─ pack_ai_input()        domain — 纯函数【新建】
  │         ├─ 一次 Qwen 调用         adapter —（复用 qwen_adapter）
  │         ├─ validate_ai_output()   domain — 纯函数【新建】
  │         ├─ _merge_ai_verdicts()   service — 逐字段：AI 成功→替换 / 失败→模板兜底
  │         └─ AI 成功 → display._aiGenerated = lang 标记（translator 检测跳过）
  │
  └─ translate_display()     domain — 加跳过逻辑（已有 _aiGenerated 则不重翻）
```

### 文件改动清单

| # | 文件 | 动作 | 行数 |
|:--:|------|------|:--:|
| 1 | `domain/display_builder.py` | 加 `pack_ai_input()` — 评估结果 + mapped → AI 输入 JSON | +60 |
| 2 | `domain/display_builder.py` | 加 `validate_ai_output()` — 校验 must_mention + 数字 + tier | +50 |
| 3 | `domain/verdict_prompts.json` | **新建** — system prompt + 输出格式 + 各语言市场适配文案 | +80 |
| 4 | `services/analyze_svc.py` | 加 `_build_with_ai()` — 编排：评估→打包→调Qwen→校验→替换 | +60 |
| 5 | `services/analyze_svc.py` | 加 `_merge_ai_verdicts()` — 逐字段独立降级 | +30 |
| 6 | `services/analyze_svc.py` | `build_result_with_display()` — lang≠zh 时走 `_build_with_ai` | ±10 |
| 7 | `domain/translator.py` | `translate_display()` — 检测 display 已有 `_aiGenerated` 标记则跳过 | +5 |

**不动：** `evaluator.py`、`_evaluator_*.py`、`product_mapper.py`、`term_glossary.json`、`config.py`、前端。

### `build_display` 不改签名

老黄修正：`_build_with_ai()` 内部自己调 `evaluate_*`，不从 `build_display` 往里传参。`evaluate_product` + `evaluate_supplier` + `evaluate_summary` < 1ms，重复调用不是问题。避免污染 `build_display` 函数签名。

### 1688 数据走 JSON 传，不拼 prompt

老黄修正：所有来自 1688 的数据（title、supplierName 等）通过 JSON 字段传递，**不拼进自然语言 prompt**。防止 1688 商品标题含 prompt 注入内容（如"忽略之前的指令"）。

```python
# ✅ 安全写法 — 1688 数据走 JSON key-value
user_msg = json.dumps({
    "eval_data": {...},        # 规则引擎产出，不来自 1688
    "to_translate": {          # 1688 原文，按 key-value 传
        "title": mapped["title"],
        "supplier_name": mapped["supplierName"]
    }
})

# ❌ 危险写法 — 禁止
user_msg = f"标题：{mapped['title']}\n供应商：{mapped['supplierName']}"
```

---

## 三、核心流程

### _build_with_ai（service 层，async）

```python
async def _build_with_ai(mapped: dict[str, Any], lang: str) -> dict[str, Any]:
    """评估 + AI 判词 + 模板兜底。"""
    
    # ① 规则引擎（纯函数，<1ms）
    product_raw = evaluate_product(mapped)
    supplier_raw = evaluate_supplier(mapped)
    summary_raw = evaluate_summary(product_raw, supplier_raw)
    
    # ② 构建 display JSON（模板判词作为兜底）
    display = build_display(mapped, lang)
    
    # ③ zh 不需要 AI
    if lang == "zh":
        return display
    
    # ④ 打包 AI 输入
    ai_input = pack_ai_input(product_raw, supplier_raw, summary_raw, mapped, lang)
    
    # ⑤ 一次 Qwen 调用（判词 + 翻译合并）
    try:
        raw = await qwen_adapter.chat([
            {"role": "system", "content": _load_prompt(lang)},
            {"role": "user", "content": json.dumps(ai_input, ensure_ascii=False)}
        ], timeout=8.0)
        ai = json.loads(raw["choices"][0]["message"]["content"])
    except Exception:
        logger.warning("AI verdict failed, fallback to template")
        return display  # 全量降级模板
    
    # ⑥ 逐字段校验替换
    display = _merge_ai_verdicts(display, ai, ai_input)
    display["_aiGenerated"] = lang  # 标记，translator 检测跳过
    
    return display
```

### _merge_ai_verdicts（service 层，纯函数）

```python
def _merge_ai_verdicts(display: dict, ai: dict, ai_input: dict) -> dict:
    """每个字段独立校验。过的替换，不过的保留模板。"""
    
    checks = [
        ("productEval.verdict", ai.get("product_verdict"),
         ai_input["must_mention"]),
        ("supplierEval.verdict", ai.get("supplier_verdict"),
         ai_input["supplier_must_mention"]),
        ("summaryLine.reason", ai.get("summary_verdict"), []),
        ("title", ai.get("title"), []),
        ("factory.supplierName", ai.get("supplier_name"), []),
    ]
    
    for path, ai_text, must_mention in checks:
        if not ai_text:
            continue
        if not validate_ai_output(ai_text, must_mention, ai_input):
            continue
        _set_nested(display, path, ai_text)
    
    return display
```

### validate_ai_output（domain 层，纯函数）

校验规则：
1. must_mention 列表中的每个关键数字/事实 → regex grep
2. 原始数字（5142、68%）→ 精确匹配，不允许四舍五入
3. tier 关键词 → 不能走样（go→"值得"、caution→"谨慎"）
4. 任何一条不过 → 返回 False → 该字段降级模板

---

## 四、降级链路

```
一次 Qwen 调用
  ├─ 成功 → JSON 解析
  │         ├─ 成功 → 逐字段校验
  │         │         ├─ 通过 → ✅ AI 判词写入 display
  │         │         └─ 失败 → ⚠️ 该字段保留模板判词
  │         └─ 失败 → ⚠️ 全量保留模板判词
  ├─ 超时 8s → ⚠️ 全量模板兜底
  └─ HTTP 错误 → ⚠️ 全量模板兜底
```

**降级后：** 非中文用户看到中文模板判词——比 AI 判词差但能用。`translate_display()` 检测 `_aiGenerated` 不存在 → 继续走原有 Qwen 翻译 title。

**最坏情况 Qwen 全挂：** 用户体验和现在一模一样。零退步。

---

## 五、风险评估

| # | 风险 | 等级 | 概率 | 影响 | 应对 |
|:--:|------|:--:|:--:|------|------|
| 1 | AI 返回非 JSON | ⚠️ 中 | 5% | 全量降级模板 | `json.loads` 失败 → 模板兜底，用户无感知 |
| 2 | AI 漏 must_mention | ⚠️ 中 | 15% | 判词缺关键信息 | 逐字段校验，单个不过只降级该字段 |
| 3 | AI 数字写错 | 🔴 高 | 10% | 用户信任崩塌 | 原始数字 regex 精确匹配，模糊化直接打回 |
| 4 | Qwen 超时 8s | 🟡 低 | 3% | 多等 8s 用模板 | 8s 超时 → 模板兜底 |
| 5 | lang=zh 误调 AI | 🟢 低 | 0% | 浪费一次调用 | lang=="zh" 直接 skip |
| 6 | AI 判词 tier 走样 | 🟡 低 | 5% | 用户困惑 | validate_tier() 检查判词结论词 ≠ 规则引擎 tier |
| 7 | Prompt 注入 | 🔴 高 | 3% | AI 被 1688 数据操控 | 1688 数据走 JSON 传，不拼自然语言 |
| 8 | 判词 + 翻译合并串任务 | ⚠️ 中 | 10% | 判词带翻译腔 | JSON 输出格式强制分区，独立校验 |
| 9 | domain 层 purity 破坏 | 🔴 高 | — | 架构腐烂 | pack/validate 是纯函数放 domain；调 Qwen 放 service |

---

## 六、开发顺序

```
Phase 1（第一天）：AI 输入输出 + 纯函数
  ├─ pack_ai_input()         — domain/display_builder.py
  ├─ validate_ai_output()    — domain/display_builder.py
  ├─ verdict_prompts.json    — domain/（新建）
  └─ 独立测试：5 case 输入 → 验证 prompt JSON 结构正确
      验证 validate 能识别"漏 must_mention""数字被改"

Phase 2（第二天）：编排 + 集成
  ├─ _build_with_ai()        — services/analyze_svc.py
  ├─ _merge_ai_verdicts()    — services/analyze_svc.py
  ├─ build_result_with_display 改道 — services/analyze_svc.py
  └─ translator skip 逻辑     — domain/translator.py

Phase 3（第三天）：测试 + 兜底验证
  ├─ 5 case 全量回归（zh/en/vi/th/id）
  ├─ 模拟：Qwen 超时 / 返回非 JSON / 漏字段 / 数字被改
  └─ 确认 zh 路径不受影响
```

---

## 七、不做的事

| 事项 | 理由 |
|------|------|
| 改 `translator.py` 核心逻辑 | 保留独立翻译能力，只加跳过检测 |
| 清理 `judge_all` 死代码 | 铁律一：不改进相邻代码 |
| 前端改任何东西 | display JSON 结构不变 |
| 加 feature flag | 模板兜底已足够安全 |
| `build_display` 加可选参数 | 1ms 重复调用不是问题，不污染签名 |

# inspect 页翻译三层审计

> 目录：① i18n 壳 → ② Glossary 覆盖 → ③ Qwen 翻译
> 生命周期：活跃 | 2026-08-05 审计 | 2026-08-05 完成 8-key 迁移

---

## 一、审计结论

| 层 | 数量 | 判断标准 | 状态 |
|----|:---:|---------|:---:|
| 🖥️ i18n 壳 | 43 key | 每种商品一样（按钮、标签、流程条、错误提示） | ✅ |
| 📖 Glossary | ~120 条 in-use | 中文由我们产出、可穷举（判词、解释、档位文案） | ✅ |
| 🤖 Qwen 翻译 | 3 字段 | 中文来自 1688、不可穷举（title / supplierName / rankText） | ✅ |

---

## 二、🖥️ i18n 壳 — 43 key

### 设计原则
- 只放"每种商品一样"的静态 UI 文本
- 不包含任何商业判断、解释文案、档位文案
- JS 用 `t('inspect.xxx')` 取值，中文 fallback 留在 HTML `data-i18n` 属性中

### Card ① 商品确认（8）

| Key | 中文 | 用途 |
|-----|------|------|
| `inspect.moqShort` | 起订 | Meta 行标签 |
| `inspect.monthlySales` | 月销 | Meta 行标签 |
| `inspect.rating` | 好评 | Meta 行标签 |
| `inspect.piecesUnit` | 件 | Meta 行 / 阶梯价单位 |
| `inspect.link1688` | 1688 产品 → | 1688 链接文字 |
| `inspect.unit` | piece | 价格单位 |
| `inspect.moq` | MOQ | 起订标签 |
| `inspect.companyName` | Company Name | 保留（供应商 ② 使用） |

### Card ① 综合结论（1）

| Key | 中文 | 用途 |
|-----|------|------|
| `inspect.summaryLabel` | 📋 综合结论 | 分区标题 |

### Card ② 产品验证（2）

| Key | 中文 | 用途 |
|-----|------|------|
| `inspect.productEvalTitle` | 📦 产品验证 | 折叠面板标题 |
| `inspect.scoreUnit` | 分 | 分数后缀（复用） |

### Card ② 供应商验证（2）

| Key | 中文 | 用途 |
|-----|------|------|
| `inspect.supplierEvalTitle` | 🏭 供应商验证 | 折叠面板标题 |
| `inspect.scoreUnit` | 分 | 分数后缀（复用，同 Card ② 产品） |

### Card ③ 拿样验货（27）

| Key | 中文 | 用途 |
|-----|------|------|
| `inspect.sampleTitle` | 📦 拿样验货 | 分区标题 |
| `inspect.flowStep1` | ① 支付定金 | 流程步骤 |
| `inspect.flowStep2` | ② 验货拍照 | 流程步骤 |
| `inspect.flowStep3` | ③ 支付尾款 | 流程步骤 |
| `inspect.flowStep4` | ④ 国际发货 | 流程步骤 |
| `inspect.viewSamplePhotos` | 📸 查看样品验货照片 ▸ | 照片链接 |
| `inspect.whatWeCheck` | 📸 我们检查什么 ▾ | 折叠面板标题 |
| `inspect.photoFront` | 正面 | 照片类目 |
| `inspect.photoSide` | 侧面 | 照片类目 |
| `inspect.photoBack` | 背面标签 | 照片类目 |
| `inspect.photoDefect` | 瑕疵特写 | 照片类目 |
| `inspect.photoPackage` | 外包装 | 照片类目 |
| `inspect.photoSku` | SKU 色卡 | 照片类目 |
| `inspect.checkTitle` | 🔍 逐项检查清单 | 分区标题 |
| `inspect.checkColor` | 颜色一致 | 检查项 |
| `inspect.checkDefect` | 无瑕疵 | 检查项 |
| `inspect.checkCount` | 数量准确 | 检查项 |
| `inspect.checkLabel` | 标签一致 | 检查项 |
| `inspect.qtyLabel` | 数量 | 费用表标签 |
| `inspect.moqLabel` | MOQ {n} pcs | 费用表标签（格式串） |
| `inspect.deposit` | 定金 | 费用表标签 |
| `inspect.productLabel` | 商品 | 费用表标签 |
| `inspect.domesticFreight` | 国内运费 | 费用表标签 |
| `inspect.balance` | 尾款 | 费用表标签 |
| `inspect.balanceNote` | 验货后支付（国际运费+服务费） | 费用表备注 |
| `inspect.totalEstimate` | 预估总计 | 费用表合计 |
| `inspect.guarantee1` | ✅ 不满意 → 全额退定金 | 保障说明 |
| `inspect.guarantee2` | ✅ 缺货 → 全额退款+找替代 | 保障说明 |
| `inspect.ctaButton` | 💬 WhatsApp 下单拿样 | CTA 按钮 |

### Card ③ 附加标签（2）

| Key | 中文 | 用途 |
|-----|------|------|
| `inspect.companyName` | 公司名称 | 供应商验证附加行标签 |
| `inspect.industryCluster` | 产业带 | 供应商验证附加行标签 |

### 错误态（3）

| Key | 中文 | 用途 |
|-----|------|------|
| `inspect.errorTitle` | 无法加载验货报告 | 错误页标题 |
| `inspect.errorMsg` | 请返回首页重新搜索 | 错误页详情 |
| `inspect.backHome` | ← 返回首页 | 错误页按钮 |

---

## 三、📖 Glossary 覆盖

### 设计原则
- 中文由我们产出、可穷举 → 走 Glossary
- display_builder 查 `term_glossary.json` 预翻译 5 语言 → 写入 display JSON
- JS 直接渲染 display JSON 中的翻译文本，**不做任何翻译或文案选择**

### Card ① 商品确认 — trust bar + badge 行 + 销售行（16 条 in-use）

| 位置 | Glossary Key | 中文示例 | display JSON 路径 |
|------|-------------|---------|------------------|
| 信任条-卖家标签 | `源头工厂` / `贸易商` 等（~14 条） | 源头工厂 | `d.trustBar.label` |
| 信任条-销量 | `trust_sold_fmt` | {n}+ 已售 | `d.trustBar.sold` |
| 信任条-年限 | `trust_years_fmt` | {n}年 1688 | `d.trustBar.years` |
| 信任条-星级标签 | `star_sufficient_label` / `_partial` / `_limited` | 推荐 | `d.trustBar.tier` |
| 信任条-说明 | `tier_sufficient_2y` ~ `tier_insufficient`（5 条） | 平台认证 + 2年+… | `d.trustBar.tierReason` |
| Badge-退货 | `7天无理由退货` | 7天无理由退货 | `d.badges[].text` |
| Badge-复购 | `badge_repurchase_fmt` | {n}% 回头率 | `d.badges[].text` |
| Badge-混批 | `支持混批` | 支持混批 | `d.badges[].text` |
| 销量行 | `sales_sold_fmt` | {n} 已售 | `d.sales.sold` |
| 销量解释 | `explain_sales_high` | 高销量意味着市场已验证… | `d.sales.explain` |
| 价格-单位 | `unit_个` ~ `unit_吨`（20 条） | 个 / pcs | `d.price.unit` |

### Card ① 综合结论（10 条）

| 位置 | Glossary Key | 中文示例 | display JSON 路径 |
|------|-------------|---------|------------------|
| 标题 | `summary_headline_go` / `_caution` | {emoji} 值得拿样 | `d.summaryLine.headline` |
| 理由 | `summary_reason_go` ~ `_skip`（4 条） | 品好、厂稳、门槛低… | `d.summaryLine.reason` |
| 判词 | `summary_go` / `_ok` / `_check` / `_skip` | 品好、厂稳、门槛低… | `d.summaryLine.verdict` |

### Card ② 产品验证（31 条）

| 位置 | Glossary Key | 中文示例 | display JSON 路径 |
|------|-------------|---------|------------------|
| D1 销量-名称 | `prod_dim_d1_name` / `_high` | 热销品 | `pe.dimensions[0].name` |
| D1 销量-标签 | `prod_dim_d1_label` | 🔥热销品 | `pe.dimensions[0].label` |
| D1 销量-数据 | `prod_dim_d1_data_fmt` | 月销 {n} | `pe.dimensions[0].data` |
| D1 销量-参考 | `prod_dim_d1_ref_fmt` | 标杆 >{n} | `pe.dimensions[0].ref` |
| D2 复购-名称 | `prod_dim_d2_name` / `_high` | 高复购 | `pe.dimensions[1].name` |
| D2 复购-标签 | `prod_dim_d2_label` | 🔄高复购 | `pe.dimensions[1].label` |
| D2 复购-数据 | `prod_dim_d2_data_fmt` | 复购率 {n}% | `pe.dimensions[1].data` |
| D2 复购-参考 | `prod_dim_d2_ref_fmt` | 标杆 >{n}% | `pe.dimensions[1].ref` |
| D3 门槛-名称 | `prod_dim_d3_name` / `_high` / `_low` | 低门槛 | `pe.dimensions[2].name` |
| D3 门槛-标签 | `prod_dim_d3_label` | 💰低门槛 | `pe.dimensions[2].label` |
| D3 门槛-数据 | `prod_dim_d3_data_fmt` | ¥{price}/{unit} · 起订 {moq} {unit} | `pe.dimensions[2].data` |
| D4 口碑-名称 | `prod_dim_d4_name` / `_high` | 口碑好 | `pe.dimensions[3].name` |
| D4 口碑-标签 | `prod_dim_d4_label` | ⭐口碑好 | `pe.dimensions[3].label` |
| D4 口碑-数据 | `prod_dim_d4_data_fmt` | 好评率 {n}% | `pe.dimensions[3].data` |
| D4 口碑-参考 | `prod_dim_d4_ref_fmt` | 标杆 ≥{n}% | `pe.dimensions[3].ref` |
| D5 退货-名称 | `prod_dim_d5_name` / `_high` | 7天退货 | `pe.dimensions[4].name` |
| D5 退货-标签 | `prod_dim_d5_label` | 🛡️7天退货 | `pe.dimensions[4].label` |
| D5 退货-数据 | `prod_dim_d5_data_ok` / `_no` | 7天无理由退货 | `pe.dimensions[4].data` |
| 组头摘要 | `prod_summary_high` ~ `_none`（4 条） | {count} 项达标… | `pe.summary` |
| 人话判词 | `prod_verdict_high` ~ `_none`（5 条） | 销量高、口碑好… | `pe.verdict` |
| 库存档位 | `stock_level_ok` / `_low` / `_unknown` | 库存充足 ✅ | `pe.stockLevel.text` |
| 空数据占位 | `no_data` | 暂无数据 / No data | `pe.dimensions[*].data` / `se.dimensions[*].data`（data 为空时） |

### Card ② 供应商验证（44 条）

| 位置 | Glossary Key | 中文示例 | display JSON 路径 |
|------|-------------|---------|------------------|
| D1 身份-名称 | `supp_dim_d1_name` / `_adv` / `_factory` / `_trader` | 认证工厂 | `se.dimensions[0].name` |
| D1 身份-标签 | `supp_dim_d1_label_adv` / `_factory` / `_trader` | 🏭认证工厂 | `se.dimensions[0].label` |
| D1 身份-数据 | `超级工厂` / `源头旗舰` / `实力工厂` / `实力商家` / `工厂直供` / `贸易商` | 实力工厂 | `se.dimensions[0].data` |
| D2 认证-名称 | `supp_dim_d2_name` / `_deep` | 深度验厂 | `se.dimensions[1].name` |
| D2 认证-标签 | `supp_dim_d2_label_deep` | 📋深度验厂 | `se.dimensions[1].label` |
| D2 认证-数据 | `supp_dim_d2_data_no_cert` + `深度验厂` / `实地认证` / `第三方验厂` / `SGS 实地认证` | 无第三方认证 | `se.dimensions[1].data` |
| D3 年限-名称 | `supp_dim_d3_name` / `_old` / `_new` | 老店 | `se.dimensions[2].name` |
| D3 年限-标签 | `supp_dim_d3_label_old` / `_new` | 📅老店 | `se.dimensions[2].label` |
| D3 年限-数据 | `supp_dim_d3_data_fmt` / `_short` | 经营 {n} 年 | `se.dimensions[2].data` |
| D3 年限-参考 | `supp_dim_d3_ref_fmt` | 标杆 ≥{n}年 | `se.dimensions[2].ref` |
| 等级文本 | `supplier_grade_verified` / `_ok` / `_caution` / `_unknown` | ✅ 可信 | `se.gradeText` |
| 组头摘要 | `supp_summary_both` / `_identity` / `_years` / `_none` | {identity} · 经营 {years} 年 | `se.summary` |
| 人话判词 | `supplier_verdict_t0` ~ `_t8`（9 条） | 认证工厂 {years} 年… | `se.verdict` |
| 帮助文字 | `supp_help_verified` / `_no_cert` / `supp_risk_no_cert` | 1688官方认证… | `se.helpTexts.*` |

### 跨卡共用 — factory explain 块（20 条 in-use）

| 位置 | Glossary Key | 中文示例 | display JSON 路径 |
|------|-------------|---------|------------------|
| 身份解释 | `explain_seller_factory` / `_trader` | 1688 平台认证的生产厂家… | `d.factory.sellerExplain` |
| 实力解释 | `explain_flags_super` / `_flagship` / `_shili` / `_self_claimed` / `_trader` | 1688 最高级别验厂认证… | `d.factory.flagsExplain` |
| 认证解释 | `explain_cert_has` / `_none` | 第三方实地验厂… | `d.factory.certExplain` |
| 排名解释 | `explain_rank_none` | 该供应商尚未进入排行榜… | `d.factory.rankExplain` |
| 公司名解释 | `explain_company_name` | 政府注册的法定名称… | `d.factory.companyNameExplain` |
| 产业带模板 | `explain_industry_fmt` | {industry}。源头产地… | `d.factory.industryCluster` |
| 产业带解释 | `explain_industry_cluster` | 源头产地，价格有竞争力。 | `d.factory.industryExplain` |
| 图标 | `emoji_factory` / `emoji_rank` | 🏭 / 🏆 | `d.factory.sellerLabel` / `rankText` |

### 产业带字典（18 条）

| Glossary Key | 中文 |
|-------------|------|
| `industry_yiwu` | 义乌/金华 — 中国小商品集散中心 |
| `industry_guangzhou` | 广州 — 服装/箱包/皮具产业带 |
| `industry_shenzhen` | 深圳 — 3C 电子/跨境电商货源 |
| `industry_jinjiang` | 晋江 — 运动服/运动鞋产业带 |
| `industry_nantong` | 南通 — 家纺产业带 |
| `industry_quanzhou` | 泉州 — 鞋服/箱包产业带 |
| `industry_dongguan` | 东莞 — 电子/玩具/模具产业带 |
| `industry_foshan` | 佛山 — 家具/陶瓷产业带 |
| `industry_hangzhou` | 杭州 — 女装/电商供应链中心 |
| `industry_wenzhou` | 温州 — 鞋业/五金/眼镜产业带 |
| `industry_ningbo` | 宁波 — 小家电/文具产业带 |
| `industry_shaoxing` | 绍兴 — 纺织/面料产业带 |
| `industry_chenghai` | 澄海 — 玩具产业带 |
| `industry_yongkang` | 永康 — 五金/杯壶产业带 |
| `industry_zhuji` | 诸暨 — 袜子/珍珠产业带 |
| `industry_chaozhou` | 潮州 — 陶瓷/卫浴产业带 |
| `industry_taizhou` | 台州 — 眼镜/模具/塑料产业带 |
| `industry_shantou` | 汕头 — 玩具/内衣/工艺品产业带 |
| `industry_fallback` | 中国制造产源地 |

### 不在 inspect 页面的条目（~40 条）

| 类型 | 示例 | 去向 |
|------|------|------|
| 旧版判词 | `verdict_product_recommend` ~ `verdict_factory_insufficient`（10 条） | report.html（旧版） |
| 拿样流程 | `verdict_sample_two_payment` | 可能用于 ③ |
| 服务标签 | `24小时发货` `48小时发货` `7天包换` `包邮` `跨境专供` `严选晚发必赔` `品质不符包赔` `免费拿样` `买家保障` `批发价` `晚发必赔` | apify 原始字段字典 |
| 数据标签 | `累计销量` `回头率` `品类排名` `暂无认证` `暂无排名` `不适用` `产业带` `源头产地` `集散地` `现货` | 可能在 report 页使用 |

---

## 四、🤖 Qwen 翻译

### 白名单（translator.py 翻译的 3 个字段）2026-08-05 精简

| # | 字段 | inspect 页使用 | 说明 |
|---|------|:---:|------|
| 1 | `title` | ✅ | Card ① 商品标题 `.p01-title` |
| 2 | `supplierName` | ✅ | Card ② 公司名称行 + `factory.supplierName` |
| 3 | `rankText` | ✅ | Card ① Meta 行 / ② 排名 extra |

> 2026-08-05 砍掉 5 字段：`shippingLocation` `factoryFlags` `certType` `specs` `skus` — inspect 页不渲染，白消耗 Qwen token。

### 翻译链路

```
mapper 输出中文
  → display_builder 写入 display JSON（此时为中文）
    → translator.py 调 Qwen 翻译 title / supplierName / rankText
      → display JSON 更新为译文
        → inspect.js 直接渲染 display JSON 中的值

Qwen 失败 → 保留中文原文 → 前端显示中文（降级）
```

---

## 五、8-key 迁移记录（2026-08-05）

以下 8 个 key 从 i18n JSON 迁入 Glossary：

| 原 i18n Key | 新 Glossary Key | 新 display JSON 路径 |
|------------|----------------|---------------------|
| `inspect.stockOk` | `stock_level_ok` | `pe.stockLevel.text` |
| `inspect.stockLow` | `stock_level_low` | `pe.stockLevel.text` |
| `inspect.stockUnknown` | `stock_level_unknown` | `pe.stockLevel.text` |
| `inspect.helpVerifiedSupplier` | `supp_help_verified` | `se.helpTexts.verified` |
| `inspect.helpNoCert` | `supp_help_no_cert` | `se.helpTexts.noCert` |
| `inspect.riskNoCert` | `supp_risk_no_cert` | `se.helpTexts.riskNoCert` |
| `inspect.helpCompanyName` | `explain_company_name`（复用已有） | `d.factory.companyNameExplain` |
| `inspect.helpIndustryCluster` | `explain_industry_cluster` | `d.factory.industryExplain` |

涉及文件：`term_glossary.json`（+7）、`display_builder.py`（+4 字段）、`inspect.js`（8 处 t() → display JSON）、`en/vi/th/id.json`（各 -8 key）

---

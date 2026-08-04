# inspect.html 页面 UI 设计方案

> 树形折叠结构，复用现有 `style.css` 设计系统 + 组件模式。
> 生命周期：提案 | 关联：[设计-验货报告页方案.md](设计-验货报告页方案.md)

---

## 一、页面结构：树形折叠

### 1.1 布局全景

```
┌──────────────────────────────────────────┐
│  ← Sourcely                    🌐 EN ▼  │  页头（renderNav）
├──────────────────────────────────────────┤
│                                          │
│  ① 商品确认                             │  始终展开，不可折叠
│  [图] 标题 · ¥2/件 · 月销8900+ · 好评  │
│                                          │
│  ┌─── ② 综合结论 ────────────────────┐  │
│  │ ┃ 🟢 值得拿样                      │  │  始终展开，不可折叠
│  │ ┃ 品好厂稳门槛低——三样全占，少见   │  │
│  │ ┃ 📦货品12分 · 🏭认证工厂          │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ▼ 📦 货品验证  ·  12/12 分  ·  满分    │  默认展开
│  ┌────────────────────────────────────┐  │
│  │ 🔥热销品  月销8900+   🟢 标杆>1k  │  │
│  │ 🔄高复购  复购67.5%   🟢 标杆>30% │  │
│  │ ...                                │  │
│  │ 💬 六个指标全部过关...             │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ▼ 🏭 供应商资质  ·  ✅可信  ·  9/9分   │  默认展开
│  ┌────────────────────────────────────┐  │
│  │ ...                                │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ▶ ⚠️ 风险提示  ·  无风险               │  默认折叠（有风险时展开）
│                                          │
│  ▶ 💰 利润空间                          │  默认折叠
│                                          │
│  ┌─── ④ 拿样发货 ──────────────────┐   │
│  │ 数量 [-] 2 [+]  起订2件           │   │  始终展开，不可折叠
│  │ ①定金 ¥14  →  ②尾款 $13-15      │   │
│  │ [💬 Chat on WhatsApp 拿样]        │   │
│  └────────────────────────────────────┘  │
│                                          │
│  Sourcely · 数据来源1688 · 2026-08-04  │  页脚（renderFooter）
└──────────────────────────────────────────┘
```

### 1.2 折叠规则

| 区块 | 折叠？ | 默认状态 | 理由 |
|:--|:--|:--|:--|
| ① 商品确认 | ❌ | 始终展开 | 用户需要确认"这是我搜的那个品" |
| ② 综合结论 | ❌ | 始终展开 | "3 秒做决定"——折叠就失去意义 |
| ③📦 货品验证 | ✅ | **展开** | 最重要的论据，用户优先看 |
| ③🏭 供应商资质 | ✅ | **展开** | 第二重要的论据 |
| ③⚠️ 风险提示 | ✅ | 有风险→**展开**，无风险→**折叠** | 无风险内容只有一行占位，折叠省空间 |
| ③💰 利润空间 | ✅ | **折叠** | 用户需要输入售价/运费才有意义，不是被动阅读 |
| ④ 拿样发货 | ❌ | 始终展开 | CTA 必须在视野内 |

### 1.3 折叠交互

```
点击组头 → toggle 展开/折叠

  ▼ 📦 货品验证  ·  12/12 分  ·  满分    ← 点击折叠
  │ ┌────────────────────────────┐ │
  │ │ (内容区，max-height 过渡)  │ │
  │ └────────────────────────────┘ │

  ▶ 📦 货品验证  ·  12/12 分  ·  满分    ← 点击展开
```

- **折叠图标：** `▼` 展开态 / `▶` 折叠态
- **点击区域：** 整行组头都可以点（≥44px 高）
- **动画：** `max-height` 过渡 0.25s，不用 JS 动画
- **折叠态保留组头一行：** 组标题 + 分数 + 一行摘要（组尾人话的缩略版，≤30 字）始终可见，让用户知道"这组大概说了什么"不点开也能感知

**折叠态组头预览：**

```
  ▶ 📦 货品验证  ·  12/12 分  ·  满分     六个指标全部过关，拿样出问题的概率很低
     emoji+名称    分数       副文字       组尾缩略（ink-3, 12px, 一行截断）
```

---

## 二、基准：复用现有设计系统

**不创建新 CSS 变量，全部引用 `style.css` `:root`：**

```css
/* ===== 语义色四档（已有变量映射）===== */
🟢 推荐 → --ok: #2F8A5B     --ok-bg: #E9F6EF
🟡 可以 → --warn: #B4832E   --warn-bg: #FBF2DE
🔴 谨慎 → --bad: #D6432F    --bad-bg: #FDEEEB
⬜ 无法  → --ink-3: #9AA1AC  --paper: #FDFBF6

/* ===== 其余色（直接用已有变量）===== */
CTA/按钮   → --seal: #D6432F    --seal-bg: #FDEEEB
品牌/链接  → --brand: #2A4C78   --brand-deep: #1E3A5F  --brand-bg: #EBF1F8
卡片       → --paper-2: #FFFFFF
页面底色   → --paper: #FDFBF6
主文字     → --ink: #232A38
次文字     → --ink-2: #5B6373
弱文字     → --ink-3: #9AA1AC
分隔线     → --line: #EDE7D8

/* ===== 间距（直接用）===== */
--s1:4px  --s2:8px  --s3:12px  --s4:16px  --s5:20px  --s6:24px  --s8:32px

/* ===== 字号（直接用）===== */
--fs-xs:11px  --fs-sm:12px  --fs:13px  --fs-md:14px  --fs-lg:16px  --fs-xl:19px

/* ===== 圆角（直接用）===== */
--r-sm:6px  --r:12px  --r-lg:18px

/* ===== 字体（直接用）===== */
--font-display  --font-body  --font-mono
```

---

## 三、逐模块详细设计

### 3.1 ① 商品确认

**复用 report.html 的 `.img-area` + `.prod-title` + `.prod-price` + `.badge-row` + `.trust-bar`。**

```html
<section class="card" id="sec-product">
  <!-- 图片区：复用 .img-area（5 缩略图 + 主图） -->
  <div class="img-area">...</div>

  <h2 class="prod-title">新款男士太阳镜...</h2>

  <p class="prod-price">¥2.00 <em>/ 件</em>
    <span class="price-moq">📦 起订 <strong>2</strong> 件</span>
    <a href="..." class="price-link" data-i18n="report.1688Link">1688 原页 →</a>
  </p>

  <div class="badge-row">
    <span class="badge-sm green">免费拿样</span>
    <span class="badge-sm gold">🏆 防护眼镜热销榜TOP3</span>
  </div>

  <div class="trust-bar">
    <span class="tb-label">源头工厂</span>
    <span class="tb-sold">月销 8,900+</span>
    <span class="tb-years">开店4年</span>
    <span class="tier-stars">★★★ 推荐</span>
  </div>

  <!-- 库存 -->
  <div class="stock-status ok">📦 库存充足 ✅</div>
</section>
```

**库存 3 态（inspect.css 新增）：**

```css
.stock-status { font-size: var(--fs-sm); padding: var(--s1) 0; font-weight: 500; }
.stock-status.ok    { color: var(--ok); }
.stock-status.warn  { color: var(--warn); }
```

---

### 3.2 ② 综合结论（不可折叠）

```html
<section class="card" id="sec-summary">
  <div class="verdict summary-go" id="summaryVerdict">
    <span class="vi"></span>
    <div>
      <div class="summary-headline">🟢 值得拿样</div>
      <div class="summary-sub">品好、厂稳、门槛低——三样全占，少见。</div>
    </div>
  </div>

  <!-- 注意事项精简版 -->
  <div class="warn" id="cautionsMini" style="display:none;"></div>

  <!-- 一行摘要 -->
  <div class="summary-meta" id="summaryMeta">📦货品12分 · 🏭认证工厂</div>
</section>
```

```css
/* ② 收尾行 */
.summary-headline {
  font-family: var(--font-display);
  font-size: var(--fs-xl);       /* 19px */
  font-weight: 700;
  color: var(--ink);
  line-height: 1.35;
}
.summary-sub {
  font-size: var(--fs-sm);       /* 12px */
  color: var(--ink-2);
  margin-top: var(--s1);
  line-height: 1.5;
}
.summary-meta {
  font-size: var(--fs-xs);       /* 11px */
  color: var(--ink-3);
  margin-top: var(--s3);
  padding-top: var(--s3);
  border-top: 1px dotted var(--line);
}

/* 四档 verdict 变体（复用 .verdict 的左边框结构） */
.verdict.summary-go   { background: var(--ok-bg);   border-left-color: var(--ok);   }
.verdict.summary-ok   { background: var(--warn-bg);  border-left-color: var(--warn); }
.verdict.summary-bad  { background: var(--bad-bg);   border-left-color: var(--bad);  }
.verdict.summary-none { background: var(--paper);    border-left-color: var(--ink-3);}
```

⚠️ **触控：** 纯展示，无交互。通过。

---

### 3.3 ③ 分项论据 — 树形折叠

**4 组内容放在一张 `.card` 里，每组折叠独立控制。**

#### 3.3.1 整体结构

```html
<section class="card" id="sec-eval">

  <!-- ===== 📦 货品验证 ===== -->
  <div class="tree-node expanded" id="node-product">
    <div class="tree-header" onclick="toggleNode('node-product')">
      <span class="tree-chevron">▼</span>
      <span class="tree-title">📦 货品验证</span>
      <span class="tree-badge go">12/12分</span>
      <span class="tree-sub">满分</span>
      <span class="tree-preview">六个指标全部过关，拿样出问题的概率很低</span>
    </div>
    <div class="tree-body">
      <!-- 维度行 + 组尾 -->
    </div>
  </div>

  <!-- ===== 🏭 供应商资质 ===== -->
  <div class="tree-node expanded" id="node-supplier">
    <div class="tree-header" onclick="toggleNode('node-supplier')">
      <span class="tree-chevron">▼</span>
      <span class="tree-title">🏭 供应商资质</span>
      <span class="tree-badge go">✅可信</span>
      <span class="tree-badge go">9/9分</span>
      <span class="tree-preview">1688认证工厂，TUV实地验过，经营4年老店</span>
    </div>
    <div class="tree-body">
      <!-- 维度行 + 组尾 -->
    </div>
  </div>

  <!-- ===== ⚠️ 风险提示 ===== -->
  <div class="tree-node" id="node-risk">
    <div class="tree-header" onclick="toggleNode('node-risk')">
      <span class="tree-chevron">▶</span>
      <span class="tree-title">⚠️ 风险提示</span>
      <span class="tree-badge ok">无风险</span>
      <span class="tree-preview">✅ 未发现明显风险</span>
    </div>
    <div class="tree-body">
      <!-- 风险条目 或 占位 -->
    </div>
  </div>

  <!-- ===== 💰 利润空间 ===== -->
  <div class="tree-node" id="node-profit">
    <div class="tree-header" onclick="toggleNode('node-profit')">
      <span class="tree-chevron">▶</span>
      <span class="tree-title">💰 利润空间</span>
      <span class="tree-preview">毛利率 71% · 单件利润 $1.40</span>
    </div>
    <div class="tree-body">
      <!-- 价格表 + 计算器 -->
    </div>
  </div>

</section>
```

#### 3.3.2 tree-header 设计（核心交互元素）

```
  折叠态:
  ▶ 🏭 供应商资质  [✅可信] [9/9分]  1688认证工厂，TUV实地验过...
  chev  名称        badge   badge    一行预览（ink-3, 截断）

  展开态:
  ▼ 📦 货品验证  [12/12分]  满分    六个指标全部过关，拿样出问题的...
  chev  名称       badge     sub    一行预览（ink-3, 截断）
```

**预览文字规则：**
- 展开态仍显示（视觉连贯）
- 折叠态显示更长的预览，让用户决定要不要点开
- 预览来自组尾人话的前 30 字
- ⚠️ 组预览来自第一条风险摘要

```css
/* ===== 树形节点 ===== */
.tree-node {
  border-bottom: 1px solid var(--line-soft, #F3EFE4);
}
.tree-node:first-child { border-top: none; }
.tree-node:last-child { border-bottom: none; }

/* 组头 — 可点击整行 */
.tree-header {
  display: flex; align-items: center; gap: var(--s2);
  padding: var(--s3) 0;
  min-height: 44px;             /* 触控最小高度 */
  cursor: pointer;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}
.tree-header:hover { background: var(--paper); }

/* 折叠箭头 */
.tree-chevron {
  font-size: 10px;
  color: var(--ink-3);
  flex-shrink: 0;
  width: 16px;
  text-align: center;
  transition: transform 0.2s;
}

/* 组名 */
.tree-title {
  font-family: var(--font-display);
  font-size: var(--fs-md);       /* 14px */
  font-weight: 700;
  color: var(--ink);
  flex-shrink: 0;
}

/* 分数/等级 badge */
.tree-badge {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);       /* 11px */
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 10px;
  color: #fff;
  flex-shrink: 0;
  white-space: nowrap;
}
.tree-badge.go   { background: var(--ok); }
.tree-badge.ok   { background: var(--warn); }
.tree-badge.bad  { background: var(--bad); }
.tree-badge.none { background: var(--ink-3); }

/* 副文字 */
.tree-sub {
  font-size: var(--fs-xs);
  color: var(--ink-3);
  font-weight: 400;
  flex-shrink: 0;
}

/* 预览文字 */
.tree-preview {
  font-size: var(--fs-xs);       /* 11px */
  color: var(--ink-3);
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ===== 折叠体 ===== */
.tree-body {
  overflow: hidden;
  transition: max-height 0.25s ease;
}
.tree-node.expanded .tree-body {
  max-height: 2000px;           /* 足够大，由内容撑开 */
}
.tree-node:not(.expanded) .tree-body {
  max-height: 0;
}
```

#### 3.3.3 维度行（展开后内容）

**复用 4 列 grid，和上版一样：**

```html
<div class="eval-dim">
  <span class="eval-dim-label">🔥热销品</span>
  <span class="eval-dim-data">月销 8,900+</span>
  <span class="eval-dim-tier">🟢</span>
  <span class="eval-dim-ref">标杆 &gt;1000</span>
</div>
```

```css
/* ③ 维度行 — 4 列 grid */
.eval-dim {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  align-items: baseline;
  gap: var(--s2);
  padding: var(--s2) 0;
  border-bottom: 1px dotted var(--line);
}
.eval-dim:last-child { border-bottom: none; }

.eval-dim-label {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}
.eval-dim-data {
  font-size: var(--fs-sm);
  color: var(--ink-2);
}
.eval-dim-tier {
  font-size: var(--fs-sm);
  flex-shrink: 0;
}
.eval-dim-ref {
  font-size: var(--fs-xs);
  color: var(--ink-3);
  white-space: nowrap;
  text-align: right;
  min-width: 72px;
}
.eval-dim-ref::before {
  content: '│ ';
  color: var(--line);
}
```

#### 3.3.4 组尾人话（展开后内容）

```html
<div class="eval-human go">
  💬 六个指标全部过关，销量、复购、口碑同时在线——这类品拿样出问题的概率很低。
</div>
```

```css
/* ③ 组尾 — 按档位配色，无斜体 */
.eval-human {
  margin-top: var(--s3);
  padding: var(--s3);
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);       /* 12px */
  line-height: 1.6;
  border-left: 3px solid;
}
.eval-human.go {
  background: var(--ok-bg);   color: #1F5C3F; border-left-color: var(--ok);
}
.eval-human.ok {
  background: var(--warn-bg);  color: #7A5A1E; border-left-color: var(--warn);
}
.eval-human.bad {
  background: var(--bad-bg);   color: #8B1A1A; border-left-color: var(--bad);
}
.eval-human.none {
  background: var(--paper);    color: var(--ink-2); border-left-color: var(--ink-3);
}
```

#### 3.3.5 平台标签 + 补充信息

```html
<div class="badge-row">
  <span class="badge-sm blue">实力商家
    <span class="term-dotted" onclick="..." data-tip="...">?</span>
  </span>
</div>
<div class="eval-extra">🏆 上榜防护眼镜热销榜TOP3</div>
<div class="eval-extra"><span class="stock-status ok">📦 库存充足 ✅</span></div>
```

```css
.eval-extra {
  font-size: var(--fs-sm);
  color: var(--ink-2);
  padding: var(--s1) 0;
}
```

#### 3.3.6 ⚠️ 风险提示组

**有风险时展开态 + 复用 `.warn`：**

```html
<div class="tree-node expanded" id="node-risk">
  <div class="tree-header" onclick="toggleNode('node-risk')">
    <span class="tree-chevron">▼</span>
    <span class="tree-title">⚠️ 风险提示</span>
    <span class="tree-badge ok">2项</span>
    <span class="tree-preview">试错成本偏高 ¥4,250 · 贸易商拿货</span>
  </div>
  <div class="tree-body">
    <div class="warn">
      <strong>💰 试错成本偏高</strong>
      试错成本约 ¥4,250 (≈ $590)。金额不低。
    </div>
    <div class="warn">
      <strong>⚠️ 贸易商拿货</strong>
      贸易商非源头工厂，拿货价可能偏高。
    </div>
  </div>
</div>
```

**无风险时折叠态：**

```html
<div class="tree-node" id="node-risk">
  <div class="tree-header" onclick="toggleNode('node-risk')">
    <span class="tree-chevron">▶</span>
    <span class="tree-title">⚠️ 风险提示</span>
    <span class="tree-badge go">无风险</span>
    <span class="tree-preview">✅ 未发现明显风险</span>
  </div>
  <div class="tree-body">
    <div class="eval-clear">✅ 未发现明显风险</div>
  </div>
</div>
```

```css
.eval-clear {
  text-align: center;
  padding: var(--s3);
  background: var(--ok-bg);
  border-radius: var(--r-sm);
  border: 1px solid var(--ok);
  font-size: var(--fs-sm);
  color: var(--ok);
}
```

#### 3.3.7 💰 利润空间

**折叠态预览显示计算结果：**

```
  ▶ 💰 利润空间    毛利率 71% · 单件利润 $1.40
```

**展开后：** 复用 `.qp-table`（价格表）+ `.cf-field`（输入框）+ `.cs-row`（当前利润结果）。

---

### 3.4 ④ 拿样发货（不可折叠）

**复用现有拿样 Tab 组件。** `.cost-phase` + `.cs-row` + `.qty-ctl` + `.sample-promise` + `.btn`。

```html
<section class="card" id="sec-sample">
  <!-- 流程条 -->
  <div class="sample-flow">
    <span class="sample-flow-step">① 付定金</span>
    <span class="sample-flow-connector"></span>
    <span class="sample-flow-step">② 验货拍照</span>
    <span class="sample-flow-connector"></span>
    <span class="sample-flow-step">③ 付尾款</span>
    <span class="sample-flow-connector"></span>
    <span class="sample-flow-step">④ 国际发货</span>
  </div>

  <!-- 数量选择 — 复用 .qty-ctl -->
  <div class="cost-form">
    <div class="cf-field">
      <label data-i18n="report.qty">数量</label>
      <div class="qty-ctl">
        <button id="qtyMinus">−</button>
        <span id="qtyVal">2</span>
        <button id="qtyPlus">+</button>
      </div>
    </div>
  </div>

  <!-- 费用明细 — 复用 .cs-row -->
  <div class="fee-box">
    <div class="cost-phase">① 定金 — 先付</div>
    <div class="cs-row"><span>商品 ¥2 × 2件</span><span>¥4.00</span></div>
    <div class="cs-row"><span>国内运费（预估）</span><span>¥10.00</span></div>
    <div class="cs-row phase-sub"><span>小计</span><span>¥14.00</span></div>

    <div class="cost-phase">② 尾款 — 验货确认后付</div>
    <div class="cs-row"><span>国际运费（预估）</span><span>$3 – $5</span></div>
    <div class="cs-row"><span>服务费</span><span>$10.00</span></div>
    <div class="cs-row phase-sub"><span>小计</span><span>$13 – $15</span></div>

    <div class="cs-row total"><span>预估总价</span><span>$16 – $18</span></div>
  </div>

  <!-- 服务保障 -->
  <p class="sample-promise">✅ 1688下单 · 收货 · 验货拍照 · 打包 · 国际物流</p>
  <p class="sample-promise">✅ 验货不满意 → 退全部定金</p>
  <p class="sample-promise">✅ 缺货/不发货 → 全额退款，帮找同款</p>
  <p class="sample-promise">✅ $10 服务费含代下单+验货+打包+送物流仓</p>

  <!-- ⑤ CTA — 复用 .btn -->
  <div class="cta-bar">
    <a href="https://wa.me/8618561525786" class="btn" target="_blank"
       data-i18n="inspect.orderBtn">💬 Chat on WhatsApp 拿样</a>
  </div>
</section>
```

**流程条样式（inspect.css 新增）：**

```css
.sample-flow {
  display: flex; align-items: center;
  margin-bottom: var(--s4);
}
.sample-flow-step {
  font-size: var(--fs-xs);
  font-weight: 600;
  padding: var(--s1) var(--s3);
  background: var(--ok-bg);
  color: var(--ok);
  border-radius: 20px;
  white-space: nowrap;
}
.sample-flow-connector {
  flex: 0 0 16px;
  height: 2px;
  background: var(--ok);
  opacity: 0.3;
}
```

**费用框（inspect.css 新增）：**

```css
.fee-box {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  padding: var(--s3) var(--s4);
  margin: var(--s3) 0;
}
```

**Sticky CTA：**

```css
.cta-bar {
  position: sticky;
  bottom: 0;
  background: var(--paper-2);
  padding: var(--s3) 0;
  padding-bottom: calc(var(--s3) + env(safe-area-inset-bottom, 0px));
  box-shadow: 0 -2px 8px rgba(0,0,0,0.06);
  z-index: 10;
}
```

---

### 3.5 术语 tooltip

```html
<span class="term-dotted" onclick="toggleTermTip(event, this)"
      data-tip="第三方机构（TUV Rheinland）实地审核工厂">
  TUV Rheinland 认证
</span>
```

```css
.term-dotted {
  border-bottom: 1px dashed var(--ink-3);
  cursor: pointer;
  padding: 6px 0;               /* 扩触控区至 ≥44px */
  position: relative;
}
```

---

### 3.6 骨架屏

```html
<main class="view" id="inspectView">
  <div class="skeleton-card" style="height:140px;"></div>
  <div class="skeleton-card" style="height:100px;"></div>
  <div class="skeleton-card" style="height:48px;"></div><!-- 折叠态 tree-header 高度 -->
  <div class="skeleton-card" style="height:48px;"></div>
  <div class="skeleton-card" style="height:48px;"></div>
  <div class="skeleton-card" style="height:48px;"></div>
  <div class="skeleton-card" style="height:200px;"></div>
</main>
```

```css
.skeleton-card {
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  margin-top: var(--s3);
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}
@keyframes skeleton-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
```

---

## 四、HTML 骨架汇总

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>源采 Sourcely — 1688 验货报告</title>
<link rel="stylesheet" href="static/css/style.css">
<link rel="stylesheet" href="static/css/inspect.css">
</head>
<body>

<div id="appNav"></div>

<main class="view" id="inspectView">

  <!-- 骨架屏（加载中） -->
  <!-- 内容区（加载后替换） -->
  <section class="card" id="sec-product"></section>     <!-- ① 不可折叠 -->
  <section class="card" id="sec-summary"></section>     <!-- ② 不可折叠 -->
  <section class="card" id="sec-eval">                  <!-- ③ 树形折叠 -->
    <div class="tree-node expanded" id="node-product">...</div>
    <div class="tree-node expanded" id="node-supplier">...</div>
    <div class="tree-node" id="node-risk">...</div>
    <div class="tree-node" id="node-profit">...</div>
  </section>
  <section class="card" id="sec-sample"></section>     <!-- ④ 不可折叠 -->

</main>

<script src="static/js/utils/lang-detect.js"></script>
<script src="static/js/utils/i18n.js"></script>
<script src="static/js/api/core.js"></script>
<script src="static/js/utils/components.js"></script>
<script>I18N.init().then(function () { renderNav('inspect'); renderFooter(); I18N.apply(); });</script>
<script src="static/js/utils/messages.js"></script>
<script src="static/js/pages/inspect.js"></script>
</body>
</html>
```

---

## 五、inspect.js 核心逻辑

```js
// —— 折叠/展开 ——
function toggleNode(nodeId) {
  var node = document.getElementById(nodeId);
  if (!node) return;
  var expanded = node.classList.contains('expanded');
  if (expanded) {
    node.classList.remove('expanded');
    node.querySelector('.tree-chevron').textContent = '▶';
  } else {
    node.classList.add('expanded');
    node.querySelector('.tree-chevron').textContent = '▼';
  }
}

// —— 初始化默认折叠状态 ——
function initTreeState(display) {
  // ③📦 默认展开
  // ③🏭 默认展开
  // ③⚠️ 有风险 → 展开，无风险 → 折叠
  // ③💰 默认折叠
  if (!display.cautions || display.cautions.length === 0) {
    document.getElementById('node-risk').classList.remove('expanded');
  }
}
```

---

## 六、文件改动清单

| 文件 | 动作 | 说明 |
|:--|:--|:--|
| `inspect.html` | **新建** | 页面结构 |
| `static/css/inspect.css` | **新建** | 专属样式，全部引用 style.css 变量 |
| `static/js/pages/inspect.js` | **新建** | 页面逻辑 + treeNode 交互 |
| `static/js/utils/components.js` | +1 行 | `NAV_LINKS` 加 `inspect` |
| `lang/i18n/{en,vi,th,id}.json` | +~14 条 | inspect 壳文案 |
| `style.css` | **不动** | |
| `report.html` / `report.js` / `report.css` | **不动** | |

---

## 七、对比：tab vs 树形折叠

| | Tab（report.html 旧方案） | 树形折叠（inspect 新方案） |
|:--|:--|:--|
| 导航 | 点 Tab 切换面板，只能看一个 | 展开/折叠任意组合，可同时看多个 |
| 信息密度 | 低——隐藏的信息用户可能永远不会点开 | 中——折叠态露预览，展开态看全部 |
| 用户心理模型 | "我要看工厂"→ 点工厂 Tab | "这个品整体怎么样？"→ 全展开扫一眼 → 关掉不关心的 |
| 移动端 | Tab 在窄屏上拥挤（3 个 Tab 平分 375px = 各 125px） | 树节点纵向排列，宽度永远是 100% |
| i18n | Tab 名称翻译量小 | tree-header 的 title/badge/preview 都需要翻译 |
| 适合场景 | 应用型页面（功能切换） | 报告型页面（逐层深入） |

**树形折叠更符合 inspect 的"验货报告"定位。**

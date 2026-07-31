# Web 前端框架护栏

> Layer 2 — 前端代码约束。AI 写任何前端代码前必须先读本文件。
>
> **行数：~130 行 | 约束不遵守就会出问题**

## 技术栈

| 维度 | 约束 |
|------|------|
| 框架 | 原生 HTML/CSS/JS（零框架依赖） |
| 模块化 | ES6 Modules |
| 样式 | CSS Variables 设计系统 |
| 图标 | Font Awesome（按需引入） |

**禁止引入：** React / Vue / TailwindCSS / jQuery / TypeScript

## API 调用规范

### 统一封装

- 所有 API 调用走 `static/js/api/core.js` 统一入口
- 自动附加 JWT token（从 `sessionStorage` 读取）
- 统一错误处理（401 跳转登录、其他错误弹 Toast）
- loading 状态在 `finally` 中清除

### Token 管理

| 操作 | 方式 |
|------|------|
| 存储 | `sessionStorage`（非 `localStorage`） |
| Key 命名 | camelCase：`accessToken` |
| 清除 | 关闭标签页即清除 |
| 前端传入 | ❌ 禁止前端传入 openid |

### 响应格式

- 标准响应：`{code: 200, data: {...}, message: "ok"}`
- 每个 `.catch()` 至少 `console.warn`

## 表单提交防重（铁律）

**提交按钮点击后立即禁用，防止用户快速双击造成重复提交。**

```js
submitBtn.disabled = true;
api.submit(data).finally(() => { submitBtn.disabled = false; });
```

**禁止：** 仅在回调中启用按钮——并发下多次请求仍会发送。

## 组件规范

### 命名

| 类型 | 规范 |
|------|------|
| 文件名 | kebab-case：`interview-qa.js` |
| 函数名 | camelCase：`showError()` |
| CSS 类名 | kebab-case：`.toast-container` |
| CSS 变量 | `--prefix-name`：`--color-primary` |

### 组件设计

- 通用组件放 `static/js/utils/components.js`，不分散在页面
- 页面逻辑放 `static/js/pages/{page}.js`
- API 调用层放 `static/js/api/{service}.js`
- 通用工具放 `static/js/utils/`（i18n, share, lang-detect 等）

### 样式

- CSS 变量集中定义在 `style.css` `:root`
- 页面专属样式单独文件，不污染全局
- 不写行内样式（性能 + 维护）

## i18n 多语言规范

### 翻译文件

```
src/web/lang/i18n/
  en.json  — 英语
  vi.json  — 越南语
  th.json  — 泰语
  id.json  — 印尼语
```

- 中文是 HTML 默认文本，**不需要 `zh.json`**
- 加载机制：`snapshotZh()` 从 HTML `[data-i18n]` 元素捕获中文原文作为 fallback
- 非中文语言 → `fetch('/lang/i18n/' + lang + '.json')`
- JSON 缺失 key → 自动降级到中文原文

### Key 命名规则（铁律）

| 类型 | 前缀 | 示例 | 范围 |
|------|------|------|------|
| 页面独有 | `{page}.*` | `index.heroTagline` `report.progressTitle` `history.emptyTitle` | 一个页面用 |
| 共享组件 | `{component}.*` | `nav.*` `footer.*` `search.*` `lang.*` | 跨页面复用 |

- 新增页面直接用页面名前缀：`help.*` `privacy.*` `terms.*`
- **禁止混用前缀** — `hero.tagline`（无前缀）是旧写法，新 key 必须带页面/组件前缀

### HTML 用法

```html
<!-- 文本替换：innerHTML -->
<span data-i18n="index.heroTagline">中文默认文本</span>

<!-- placeholder 替换 -->
<input data-i18n-placeholder="search.placeholder" placeholder="中文占位符">

<!-- 含 HTML 的翻译值（如带链接） -->
<p data-i18n="index.valueProp">粘贴 <a href="...">链接</a> → 查看结果</p>
```

### 新增页面 i18n 步骤

1. HTML 所有展示文案加 `data-i18n` 属性，中文原文留在标签内
2. key 按页面前缀命名（如 `help.step1Title`）
3. 在 4 个语言 JSON 文件中各追加对应翻译
4. 页面底部 `<script>` 加载顺序：`lang-detect.js` → `i18n.js` → `api/core.js` → `components.js`
5. 初始化：`I18N.init().then(function () { renderNav(...); renderFooter(); I18N.apply(); });`

### 新增语言

1. 复制 `en.json` → `{lang}.json`
2. 翻译所有 value
3. `i18n.js` 的 `LOCALES` 加一行
4. `lang-detect.js` 的 supported 列表加语言代码

## 目录约定

- 页面入口：`src/web/{page}.html`
- JS 分目录：`api/` 调用层、`pages/` 页面逻辑、`utils/` 通用工具
- CSS 分页：`static/css/{page}.css`，不污染全局

## 禁止事项（铁律）

| 禁止 | 原因 |
|------|------|
| ❌ localStorage 存敏感信息 | 关闭标签页不清除 |
| ❌ 前端传入用户身份 | 必须从后端 `request.state` 获取 |
| ❌ HTML 内联 JS 事件 | `onclick=` 难维护 |
| ❌ 前端实现业务逻辑 | 只做展示和交互 |
| ❌ 未清理的 SSE/WebSocket / 定时器 | 页面离开必须 `close()` / `clearInterval` |
| ❌ 未清理的事件监听器 | `addEventListener` 后必须 `removeEventListener` |

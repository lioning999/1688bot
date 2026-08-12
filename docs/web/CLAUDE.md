# Web 前端框架护栏
> Layer 2 — 前端代码约束。写前端代码前必读。
> 最后更新：2026-08-08

---

## 数据管线（inspect.js 渲染流程）

```
用户操作（?sample= / ?offerId= / ?url= / ?taskId= / 恢复轮询）
  → _enterSearching() — 统一入口：设 _searching + 禁按钮 + 显骨架屏
  → 数据加载：
      sample  → fetch display JSON
      offerId → sessionStorage 缓存 → DB（已登录）→ Apify（降级）
      url     → API.analyze → pollTask（2s 轮询，上限 60 次）
      taskId  → pollTask 继续轮询
  → render(result) — display 缺失时 verdict 兜底
  → 5 卡片渲染：商品确认 → 综合结论 → 产品验证 → 供应商验证 → 拿样验货
  → resetSearchBtn() + hideSkeleton() + 清理 sessionStorage
```

---

## 一、架构边界

| 层 | 文件 | 职责 |
|----|------|------|
| 页面入口 | `{page}.html` | DOM 结构 + `data-i18n` + script 加载顺序 |
| 页面逻辑 | `static/js/pages/{page}.js` | 渲染 + 交互 + 状态管理 |
| API 层 | `static/js/api/core.js` | **唯一 HTTP 出口**，自动 JWT + 统一错误处理 |
| 消息出口 | `static/js/utils/messages.js` | **唯一 Toast/提示出口**，msg_code → i18n |
| 多语言 | `static/js/utils/i18n.js` | 翻译加载 + 应用 + 价格格式化 |
| 通用组件 | `static/js/utils/components.js` | nav / footer / Toast（跨页面复用） |

**技术栈：** 原生 HTML/CSS/JS（零框架依赖）。全局 IIFE 模块通过 `window.XXX` 暴露。
**禁止引入：** React / Vue / TailwindCSS / jQuery / TypeScript / npm 依赖。

**页面 script 加载顺序（铁律）：**
```
lang-detect.js → i18n.js → api/core.js → messages.js → components.js → pages/{page}.js
```

---

## 二、inspect.js 核心约束（七条）

违反任意一条 → 页面状态混乱。每条都出过线上 bug。

### ① _enterSearching 入口统一

**所有数据加载路径必须通过 `_enterSearching(hintText)` 统一进入。**
sample / offerId / taskId / url / 恢复轮询 — 五条路径都走这一个入口，禁止各自独立操作 DOM。

### ② _searching 防重

**全局标志 `_searching`：** 入口设 `true`，`resetSearchBtn()` 恢复 `false`。
搜索按钮 click / Enter 事件开头必须 `if (_searching) return;`。
并发下多次点击 → 只发一次请求。

### ③ 轮询清理

**页面离开前必须 `clearTimeout(_pollTimer)`：**
```js
window.addEventListener('beforeunload', function () {
  if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }
});
```
轮询上限 60 次（2 分钟）。超时 → resetSearchBtn + hideSkeleton + Messages.error。

### ④ display 兜底

**render() 必须检查 `result.display` 是否存在。** 缺失 → 从 `result.verdict_product/factory/sample` 构造最小 display：
```js
result.display = {
  title: result.title || '',
  productEval: { verdict: result.verdict_product || '', grade: 'none' },
  supplierEval: { verdict: result.verdict_factory || '', grade: 'none' },
  summaryLine: { headline: result.verdict_product || '', reason: '' }
};
```

### ⑤ 状态复位

**任何失败/完成路径必须同时调用：**
```js
resetSearchBtn();   // _searching=false + 按钮恢复 + hint 复位
hideSkeleton();     // 隐藏骨架屏
sessionStorage.removeItem('lastTaskId');  // 失败时清理
```
禁止留死状态：骨架屏永远不消失、按钮永远禁用、hint 永远"分析中..."。

### ⑥ sessionStorage 协议

| Key | 用途 | 何时清理 |
|-----|------|---------|
| `lastTaskId` | 未完成轮询恢复 | 任务完成/失败时 |
| `lastResult_{offerId}` | 秒恢复缓存 | 同会话 |
| `saved_{offerId}` | 已保存标记 | 同会话 |
| `accessToken` | JWT（core.js 读取） | 关闭标签页清除 |
| `user` | 当前登录用户信息（JSON） | 退出登录时清除 |
| `sourcely_lang` | 手动语言选择（实际存 localStorage） | persistent |

**禁止：** 前端传入 user_id / openid。禁止 localStorage 存 token。

### ⑦ XSS 防御

**任何后端/URL/用户输入的数据插入 innerHTML 前，必须过 `escHtml()`：**
```js
function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
```
HTML 内联事件（`onclick=`）禁止 → 统一在 JS 中 `addEventListener`。

---

## 三、API 调用规范

- **唯一入口：** `static/js/api/core.js`。禁止页面内直接 `fetch()`。
- **自动 JWT：** `authHeaders()` 从 sessionStorage 读 `accessToken`，自动附加 `Authorization: Bearer`。
- **错误处理：** core.js 统一处理 401/403/5xx → 委托 Messages 显示 Toast。页面层只处理 `code===200`，不重复弹 Toast。

| 方法 | 用途 |
|------|------|
| `API.analyze(url, lang)` | 启动分析（POST） |
| `API.getTask(taskId)` | 轮询任务状态（GET） |
| `API.getReport(offerId, lang)` | 查已保存报告 |
| `API.saveReport(offerId)` | 保存报告到 DB |
| `API.getConfig()` | 获取汇率/配置 |

---

## 四、消息系统

**`messages.js` 是前端唯一消息出口。** 禁止 `alert()` / 手写 toast HTML。

```js
Messages.success('SAVE_OK', 'Saved!');       // 成功，自动消失
Messages.warning('LOGIN_REQUIRED', '...');    // 警告，sticky
Messages.error('NETWORK_ERROR', '...');       // 错误，sticky
```

- `msg_code` 对应 i18n key `msg.{code}`，翻译在 4 语言 JSON 中
- 后端新增 msg_code → 前端 4 语言 JSON 同步新增 `msg.{code}`

---

## 五、i18n 多语言规范

**中文是 HTML 默认文本，不需要 `zh.json`。**
非中文语言 → `fetch('/lang/i18n/' + lang + '.json')`，缺失 key 自动降级到中文原文。

### Key 命名

| 类型 | 前缀 | 示例 |
|------|------|------|
| 页面独有 | `{page}.*` | `inspect.moq` `history.emptyTitle` `index.heroTagline` |
| 共享组件 | `{component}.*` | `nav.*` `search.*` `lang.*` |
| 消息 | `msg.*` | `msg.SAVE_OK` `msg.NETWORK_ERROR` |

**禁止混用：** 无前缀 key（如 `hero.tagline`）是旧写法，新 key 必须带前缀。

### 新增页面步骤

1. HTML 所有文案加 `data-i18n` + 中文默认文本
2. key 按页面前缀命名
3. 4 语言 JSON 各追加翻译
4. 页面 script 按加载顺序排列

### 新增语言

1. 复制 `en.json` → `{lang}.json`
2. 翻译所有 value
3. `i18n.js` `LOCALES` 加一行
4. `lang-detect.js` supported 列表加语言代码

---

## 六、禁止事项

| 禁止 | 原因 |
|------|------|
| ❌ 页面内直接 `fetch()` | 必须走 `api/core.js` |
| ❌ 页面内 `alert()` / 手写 toast | 必须走 `messages.js` |
| ❌ 前端传入 user_id / openid | 后端从 `request.state` 获取 |
| ❌ `innerHTML` 不经 `escHtml()` 赋值 | XSS |
| ❌ `localStorage` 存 token | 关闭标签页不清除 |
| ❌ HTML 内联 `onclick=` | 统一 `addEventListener` |
| ❌ 未清理的 `setTimeout` / `setInterval` | beforeunload 清理 |
| ❌ 新增页面不注册 i18n | 4 语言 JSON 必须同步 |
| ❌ 前端实现业务逻辑 | 只做展示和交互 |

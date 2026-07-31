# API 后端框架护栏
> Layer 2 — Python/FastAPI 专属约束。写后端代码前必读。
> 最后更新：2026-07-21 — Sourcely V1（Google OAuth + Apify + 零 AI）

---

## 一、架构边界（铁律）

```
请求 → CORS → JWT 中间件 → routes/（Pydantic 参数校验）
       → services/（业务编排）
         → adapters/（外部 API）
         → repositories/（数据库）
         → domain/（纯逻辑）
```

| 层 | 职责 | 禁止 |
|----|------|------|
| **routes/** | 参数校验 + 调用 service + 标准返回 | 直接操作数据库、包含业务逻辑、直接调外部 API |
| **services/** | 业务编排，注入 adapter + repository | 手写 SQL、手管连接、raise HTTPException |
| **adapters/** | 外部 API 封装，一个服务一个文件 | 包含业务逻辑、操作数据库 |
| **repositories/** | 数据库操作，连接生命周期自管 | 包含业务逻辑、调外部 API |
| **domain/** | 纯函数，零外部依赖 | 调数据库、调 API、读环境变量 |
| **utils/** | 纯工具（异常/JWT/日志） | 依赖 services/ 或 routes/ |

- 同层不互调：公共逻辑提取到 domain/
- API 路径不使用 `/api/v1/` 前缀
- **文件 ≤ 200 行（建议），service 方法 ≤ 50 行（铁律）**

## 二、代码规范 + 命名一致性

- PEP8，4 空格缩进；所有函数完整类型注解；async 边界签名可见
- **import 放文件顶部，禁止函数体内 import**（stdlib 除外，需注释说明）
- **禁止硬编码配置值（铁律）**——以下值统一放 `config.py` 通过 `Config.XXX` 引用，代码中不写死：
  `汇率` `URL 模板` `超时秒数` `配额/限制数值` `第三方服务端点` `密钥`

### Python 类型注解最低标准（新建/修改文件时强制）

- **禁止裸 `dict`/`list`** — 所有函数签名、变量声明必须带完整泛型参数：
  `dict[str, Any]`、`list[dict[str, Any]]`、`tuple[float, dict[str, Any]]`
- **第三方库无 stubs** → `import xxx  # type: ignore[import-untyped]`
- `from typing import Any` — 只要用了 `dict[str, Any]` 就必须 import，IDE 不报错 ≠ 不需要

| 类型 | 规范 | 示例 |
|------|------|------|
| Routes | `routes/{资源}.py` | `routes/auth.py`、`routes/history.py` |
| Services | `services/{资源}_svc.py` | `services/analyze_svc.py` |
| Repositories | `repositories/{表名}_repo.py` | `repositories/user_repo.py` |
| Adapters | `adapters/{服务名}.py` | `adapters/google_auth.py` |
| Domain | `domain/{功能}.py` | `domain/verdict_engine.py` |
| 函数名 | 动词 + 名词 | `create_token()`、`get_by_google_id()` |

## 三、响应格式

**唯一标准：** `{code: 200, data: ..., message: "ok", msg_code: "..."}` — code = HTTP 状态码

| 场景 | 格式 |
|------|------|
| 正常 | `{code: 200, data: {...}, message: "ok", msg_code: "..."}` |
| 错误 | `{code: 4xx/5xx, data: null, message: "错误描述", msg_code: "..."}` |
| 登录回调 | `RedirectResponse`（302 → 首页带 token） |

### msg_code 铁律（V2 新增）

**每一条可能展示给用户的响应都 MUST 带 `msg_code`。** 它是对前端 `messages.js`（唯一消息出口）的契约字段。

| 规则 | 说明 |
|------|------|
| 所有错误 MUST 走 `raise AppError` | 禁止 `return {code:4xx}` / `raise HTTPException` / catch-all 硬编码 |
| `AppError` 子类 MUST 带 `msg_code` | 在 `utils/exceptions.py` 子类构造函数中设默认值 |
| 成功返回 MUST 带 `msg_code` | routes 中 `return {code:200}` 手动加 |
| 中间件 401 必须加 `msg_code` | `JSONResponse` content dict 中手动加 |
| `services/analyze_svc.py` task dict 的 error/warning 加在 dict 里 | 不是抛异常，是写入 `_tasks`，route 读出后返回前端 |
| `message` 字段保留 | 前端无 `msg_code` 对应翻译时降级显示 `message` |
| 后端禁止翻译 `msg_code` | 翻译在前端 `messages.js` 通过 i18n 完成 |

**能返回用户消息的 7 个文件（铁律清单）：**
```
utils/exceptions.py    — AppError + msg_code 定义
main.py                — 422/500 handler
routes/analyze.py      — 启动/轮询/保存
routes/history.py      — 历史 CRUD
routes/proxy.py        — 图片代理
middleware.py          — JWT 401
services/analyze_svc.py — task dict error/warning
```
**新增/修改路由如果产生用户可见消息 → 必须同步更新此清单 + 前端 i18n JSON。**

## 四、认证中间件

```
CORS（最外层，OPTIONS 放行）→ JWT（内层，Bearer token 校验）
```

- **认证方式：** Google OAuth 2.0 + 自签 JWT（HS256，7 天过期）
- **PROTECTED_PREFIXES = ["/api/"]** — 需 JWT 认证
- **EXEMPT_PATHS = ["/api/auth/google/login", "/google-callback", "/docs", "/openapi.json", "/health"]**
- 不在前缀内的路径（`/` 静态文件等）默认放行
- 中间件返回 JSONResponse，不抛异常（抛异常被 Starlette 转 500）
- **用户身份从 `request.state.user_id` 获取，禁止前端传入 user_id**

### Google 登录（服务端 OAuth 2.0）

1. `GET /api/auth/google/login` → 302 到 Google 授权页
2. 用户授权 → `GET /google-callback?code=xxx`
3. 后端 code 换 id_token（调 Google token 端点）
4. 验证 id_token（aud / exp / iss）→ Upsert users → 签发自签 JWT
5. 302 重定向首页，token 通过 URL query 传递
- Token 存前端 `sessionStorage`（非 `localStorage`）
- Client ID / Secret / Redirect URI → `.env` 中 `GOOGLE_*` 系列变量

## 五、数据库

- MySQL 8.0，`utf8mb4`，InnoDB，aiomysql 连接池 5-20
- 库名 `sourcely_DB`；**autocommit=False**；SQL 100% 参数化（`%s`）
- **DictCursor 铁律：** `conn.cursor(aiomysql.DictCursor)` 返回 dict
- 表结构以 `db/schema.sql` 为准（2 表：users / analysis，子表已废弃见 V1.3）
- `analysis.offer_id + user_id` 联合唯一；子表 `ON DELETE CASCADE`；status: `pending → running → done/failed`

## 六、Repository 层

一个 repository 对应一张表。每个方法自管连接（get → try → commit/rollback → finally close）。标准形状见 `repositories/analysis_repo.py`。

- 使用 `aiomysql.DictCursor`，返回 dict 或 None
- 不包含业务逻辑，不调外部 API
- 方法名：`get_` / `create_` / `update_` / `delete_` / `count_` / `exists_`

## 七、Adapter 层

一个外部服务一个文件。所有外部异常包装为 `ExternalServiceError`。

| 文件 | 服务 | 关键细节 |
|------|------|---------|
| `adapters/google_auth.py` | Google OAuth 2.0 | 模块级单例 `google_auth_adapter` |
| `adapters/apify_adapter.py` | Apify 1688 Scraper | `ApifyClientAsync` SDK，v3.x 无 `async with`，模块级单例 `apify_adapter` |
| `adapters/qwen_adapter.py` | Qwen3-Flash API | HTTP 调用封装，模块级单例 `qwen_adapter` |

## 八、Domain 层

零外部依赖的纯函数。不 import 数据库/HTTP/FastAPI/环境变量。

```
domain/
├── cache.py                  # 内存缓存（TTL 30min，LRU 淘汰，上限 500 条）
├── display_builder.py        # Display JSON 构建器：全部走 term_glossary.json 查表，4 语言预翻译
├── product_mapper.py         # Apify 原始 JSON → 标准化数据映射（输出 glossary KEY，纯函数）
├── rate_limiter.py           # 滑动窗口全局限流（30 次/分钟）
├── term_glossary.json        # 术语/模板/解释/判词/产业带 字典 — 唯一翻译数据源（~100 条 × 4 语言）
├── translator.py             # Qwen 翻译：仅翻译 1688 原始数据（title/supplierName/shippingLocation 等 6 字段）
├── translator_prompts.json   # 翻译 prompt 模板（system + template + forbidden）
├── urls.py                   # 1688 URL 解析（extract_offer_id / is_valid_1688_url）
└── verdict_engine.py         # 规则引擎：输出 {key, params}，判词文案从 glossary 查表
```

## 九、异常体系

`utils/exceptions.py` — 5 种异常，全局处理器自动转换 `AppError` → `{code, data, message}`。

**services/ 层规则：** 只抛 AppError 子类，禁止 raise HTTPException / ValueError。

| 场景 | 异常 |
|------|------|
| 参数校验失败 | `ValidationError` |
| 资源不存在 | `ResourceNotFoundError` |
| 外部服务挂了 | `ExternalServiceError` |
| 配额不足 | `InsufficientQuotaError` |

**异常透传：Adapter 已抛 AppError 时，Service 层 `raise` 原样透传，禁止重新包装。**

## 十、Apify 集成

- **Actor：** `zen-studio~1688-wholesale-scraper`
- **SDK：** `ApifyClientAsync` — `actor.call(run_input, wait_duration)` → `dataset.list_items()`
- **超时：** 90 秒（`APIFY_WAIT_SECONDS`）；**降级：** 超时/失败 → 过期缓存兜底 → 无缓存则拒绝
- **成本控制：** offer_id 缓存 30min TTL + 全局限流 30 次/分钟

## 十一、V1 AI 使用限制

**V1 判词仍用纯规则引擎，不引入 LLM。** 动态内容翻译可使用 Qwen3-Flash（OpenAI 兼容接口）将中文字段翻译为目标语言（en/vi/th/id）。翻译用于 display JSON 的 Path 3 字段，不属于业务逻辑。翻译失败降级回中文原文，不影响主流程。

## 十二、并发控制 + 资源清理

**路由层防重：** 同资源并发写 → 返回 409 "请求处理中"。禁止 `SELECT COUNT → INSERT` 做幂等。
**请求合并：** 同 offer_id 正在分析中 → 复用已有 Task 结果，不启新 run。实现见 `services/analyze_svc.py:_pending`。

| 资源 | 清理方式 |
|------|---------|
| DB 连接池 | 应用关闭时 `close_pool()`（main.py lifespan） |
| 全局 dict 缓存 | 大小上限 + LRU 淘汰 |
| asyncio.Task | 创建前先 cancel 旧任务 |

## 十三、安全底线

- 密钥从环境变量读取，缺失启动报错（`Config.validate()`）
- `.env` 不提交 Git，`.env.example` 可提交
- **任何业务判断（数据归属、付费状态）必须后端独立校验**
- Google id_token 验证：`aud == CLIENT_ID` + `exp > now` + `iss in ('accounts.google.com', 'https://accounts.google.com')`
- Token 禁止进日志、禁止进响应体（除登录接口外）

## 十四、日志规范

`utils/logger.py` — 文件轮转 + 控制台双输出。脱敏：email 前 3 位 + `***@***`，token 只记长度。

| 级别 | 场景 |
|------|------|
| `info` | 登录/注册、Apify 状态变化、关键业务节点 |
| `warning` | 可恢复异常 |
| `error` | 需人工介入（Google 验证失败、DB 连接池失败） |
| `debug` | JWT 验签、DB 连接获取/释放 |

## 十五、配置与构建

```bash
cd src/api
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8008
# 前端通过 FastAPI 静态文件挂载，访问 http://localhost:8008
```

- `load_dotenv` 只在 `config.py` 调用一次
- `config.py` 默认值必须与 `.env.example` 一致
- 新增配置项必须同时在 `config.py` 和 `.env.example` 添加
- **改配置名/接口/文件名/路由时，必须同步更新本文件所有引用**（铁律）
- 密钥缺失 → `Config.validate()` 启动报错

## 十六、资源约束速查

| 约束项 | 值 | 位置 |
|--------|-----|------|
| DB 连接池 | 5-20 | `database.py` |
| JWT 有效期 | 7 天 | `JWT_EXPIRE_MINUTES` |
| Google OAuth Redirect | `GOOGLE_REDIRECT_URI` | `.env` |
| Apify 超时 | 90 秒 | `config.py` `APIFY_WAIT_SECONDS` |
| 分析缓存 TTL | 30 分钟 / 500 条 | `domain/cache.py` |
| 全局限流 | 30 次/分钟 | `domain/rate_limiter.py` |
| 每日免费分析 | 3 次 | `config.py` `APIFY_DAILY_FREE_LIMIT` |

## 十七、死代码 + 测试

- 删函数/类/变量前 grep 全项目确认零引用
- 测试文件放 `tests/`，按层分子目录；测行为不测实现
- Domain 层测试不需要 mock；Adapter 用 MockAdapter；Repository 用测试数据库

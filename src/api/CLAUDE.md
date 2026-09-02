# API 后端框架护栏
> Layer 2 — Python/FastAPI 专属约束。写后端代码前必读。
> 最后更新：2026-08-17 — V2（规则引擎 + AI 判词 + Apify）

---

## 简短作答（默认）

默认简短作答，别啰嗦。结论 + 必要理由即可，用户要详细时才展开。

## 数据管线（处理流程）

```
1688链接
  → DB 检查复用（repositories/analysis_repo.py · get_by_offer_id）
      命中 raw_json + 当前语言 display_i18n → 直接返回，跳过后续全部
      命中 raw_json 但缺当前语言 → 跳过 Apify，走 map_raw 重建 + 追加翻译
      未命中 → 走 Apify
  → Apify 抓取原始数据（adapters/apify_adapter.py）
  → 自动落库 raw_json（analysis 表）
  → 数据映射 map_raw（domain/data/mapper.py）
  → 规则引擎评判 evaluate（domain/evaluate/：产品 12 规则 + 供应商 6 规则 → 4 档）
  → build_result_with_display（services/ai_verdict_svc.py）：
      ├─ zh → 模板 display（domain/display/builder.py）
      └─ 非zh(含ru) → build_with_ai（services/ai_verdict_svc.py）
              → 母语 system prompt（domain/display/verdict_prompts.json）
              → Qwen 一次调用出判词+翻译（adapters/qwen_adapter.py）
  → display_i18n 落库（analysis 表，仅当前语言）
  → Display JSON → 前端渲染
```

> 改流程 → 同步更新此管线。

---

## 一、架构边界

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

---

## 二、代码规范

- **import 放文件顶部，禁止函数体内 import**（stdlib 除外，需注释说明）
- **禁止硬编码配置值** — 以下值统一放 `config.py` 通过 `Config.XXX` 引用：
  `汇率` `URL 模板` `超时秒数` `配额/限制数值` `第三方服务端点` `密钥`
- **禁止裸 `dict`/`list`** — 所有函数签名必须带完整泛型参数：
  `dict[str, Any]`、`list[dict[str, Any]]`
- 第三方库无 stubs → `import xxx  # type: ignore[import-untyped]`
- `from typing import Any` — 只要用了 `dict[str, Any]` 就必须 import

### 命名

| 类型 | 规范 | 示例 |
|------|------|------|
| Routes | `routes/{资源}.py` | `routes/auth.py`、`routes/history.py` |
| Services | `services/{资源}_svc.py` | `services/analyze_svc.py`、`services/ai_verdict_svc.py` |
| Repositories | `repositories/{表名}_repo.py` | `repositories/user_repo.py` |
| Adapters | `adapters/{服务名}.py` | `adapters/apify_adapter.py` |
| Domain | `domain/{子目录}/{功能}.py` | `domain/display/builder.py` |

---

## 三、Python 专属铁律

> 以下规则从根 CLAUDE.md 移入 — 仅写后端时加载，节省前端上下文。

- **所有函数完整类型注解**
- 改 Python 常量 → grep 所有 import 和使用点
- 改 API 路由/响应格式 → grep 前端所有调用，确认前端同步
- 改判词逻辑 → 改 `domain/evaluate/` 即可。前端直接展示 display JSON 中的判词，无双端同步问题
- 改 `config.py` → 确认 `.env.example` 同步
- 新建文件 → 注册到入口 + 顶部一行描述用途

---

## 四、响应格式

**唯一标准：** `{code: 200, data: ..., message: "ok", msg_code: "..."}` — code = HTTP 状态码

| 场景 | 格式 |
|------|------|
| 正常 | `{code: 200, data: {...}, message: "ok", msg_code: "..."}` |
| 错误 | `{code: 4xx/5xx, data: null, message: "错误描述", msg_code: "..."}` |
| 登录回调 | `RedirectResponse`（302：插件流 `chromiumapp.org?token=xxx`，Web 流 cookie 传 token 不进 URL） |

### msg_code 铁律

**每一条可能展示给用户的响应都 MUST 带 `msg_code`。** 它是对前端 `lib/i18n.js` + `lang/{zh,en,vi,th,ru}.json`（唯一消息出口）的契约字段。

| 规则 | 说明 |
|------|------|
| 所有错误 MUST 走 `raise AppError` | 禁止 `return {code:4xx}` / `raise HTTPException` / catch-all 硬编码 |
| `AppError` 子类 MUST 带 `msg_code` | 在 `utils/exceptions.py` 子类构造函数中设默认值 |
| 成功返回 MUST 带 `msg_code` | routes 中 `return {code:200}` 手动加 |
| 中间件 401 必须加 `msg_code` | `JSONResponse` content dict 中手动加 |
| `services/analyze_svc.py` task dict 的 error/warning 加在 dict 里 | 不是抛异常，是写入 `_tasks`，route 读出后返回前端 |
| `message` 字段保留 | 前端无 `msg_code` 对应翻译时降级显示 `message` |
| 后端禁止翻译 `msg_code` | 翻译在前端 `lib/i18n.js`（`lang/{zh,en,vi,th,ru}.json`）通过 i18n 完成 |

**新增/修改路由如果产生用户可见消息 → 必须同步更新 `/file-map` skill + 前端 i18n JSON。**

---

## 五、认证中间件

```
CORS（最外层，OPTIONS 放行）→ JWT（内层，Bearer token 校验）
```

- **认证方式：** Google OAuth 2.0 + 自签 JWT（HS256，90 天过期）
- **PROTECTED_PREFIXES = ["/api/"]** — 需 JWT 认证
- **EXEMPT_PATHS = ["/api/auth/google/login", "/google-callback", "/docs", "/openapi.json", "/health"]**
- **EXEMPT_PREFIXES = ["/api/analyze", "/api/config", "/api/proxy", "/api/quota"]**（未登录可用）
- 不在前缀内的路径（`/` 静态文件等）默认放行
- 中间件返回 JSONResponse，不抛异常（抛异常被 Starlette 转 500）
- **用户身份从 `request.state.user_id` 获取，禁止前端传入 user_id**

---

## 六、异常体系

`utils/exceptions.py` — 4 种异常，全局处理器自动转换 `AppError` → `{code, data, message}`。

**services/ 层规则：** 只抛 AppError 子类，禁止 raise HTTPException / ValueError。

| 场景 | 异常 |
|------|------|
| 参数校验失败 | `ValidationError` |
| 资源不存在 | `ResourceNotFoundError` |
| 外部服务挂了 | `ExternalServiceError` |
| 配额不足 | `InsufficientQuotaError` |

**异常透传：Adapter 已抛 AppError 时，Service 层 `raise` 原样透传，禁止重新包装。**

---

## 七、并发控制 + 资源清理

**请求合并：** 同 offer_id 正在分析中 → 复用已有 Task 结果，不启新 run。实现见 `services/analyze_svc.py:_pending`。

| 资源 | 清理方式 |
|------|---------|
| DB 连接池 | 应用关闭时 `close_pool()`（main.py lifespan） |
| asyncio.Task | 创建前先 cancel 旧任务 |

---

## 八、安全底线

- 密钥从环境变量读取，缺失启动报错（`Config.validate()`）
- `.env` 不提交 Git，`.env.example` 可提交
- **任何业务判断（数据归属、付费状态）必须后端独立校验**
- Google id_token 验证：`aud == CLIENT_ID` + `exp > now` + `iss in ('accounts.google.com', 'https://accounts.google.com')`
- Token 禁止进日志、禁止进响应体（除登录接口外）

---

## 九、日志规范

`utils/logger.py` — 文件轮转 + 控制台双输出。脱敏：email 前 3 位 + `***@***`，token 只记长度。

| 级别 | 场景 |
|------|------|
| `info` | 登录/注册、Apify 状态变化、关键业务节点 |
| `warning` | 可恢复异常 |
| `error` | 需人工介入（Google 验证失败、DB 连接池失败） |
| `debug` | JWT 验签、DB 连接获取/释放 |

---

## 十、配置与构建

- `load_dotenv` 只在 `config.py` 调用一次
- `config.py` 默认值必须与 `.env.example` 一致
- 新增配置项必须同时在 `config.py` 和 `.env.example` 添加
- **改配置名/接口/文件名/路由时，必须同步更新本文件所有引用**（铁律）
- 密钥缺失 → `Config.validate()` 启动报错

---

## 十一、资源约束速查

| 约束项 | 值 | 位置 |
|--------|-----|------|
| DB 连接池 | 5-20 | `database.py` |
| JWT 有效期 | 90 天 | `JWT_EXPIRE_MINUTES` |
| Google OAuth Redirect | `GOOGLE_REDIRECT_URI` | `.env` |
| Apify 超时 | 90 秒 | `config.py` `APIFY_WAIT_SECONDS` |
| 历史记录上限 | free=20 paid=100（自动落库，超限 FIFO 清理未收藏） | `Config.HISTORY_FREE_MAX` `HISTORY_PAID_MAX` |
| 全局限流 | 30 次/分钟 | `domain/infra/rate_limiter.py` |
| 用户分析配额 | 注册送10次 + 每日补地板（free=3 paid=20），懒重置 | `Config.SIGNUP_BONUS_QUOTA` `DAILY_FREE_QUOTA` `DAILY_PAID_QUOTA` |

---

## 十二、测试

- 测试文件放 `tests/`，按层分子目录；测行为不测实现
- Domain 层测试不需要 mock；Adapter 用 MockAdapter；Repository 用测试数据库

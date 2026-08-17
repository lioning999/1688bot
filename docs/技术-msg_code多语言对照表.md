# msg_code 多语言对照表

> 后端 23 个 msg_code（21 错误 + 2 成功）→ 前端 4 语言文案。前端 i18n key = `msg.{CODE}`。
> 翻译归属：铁律九 层① 前端 i18n。改错误提示前先查此表。
> 权威源：后端 `routes/*.py` + `services/*.py` + `utils/exceptions.py` 的 msg_code 定义；前端 `src/chrome-ext/lang/*.json`。
> 最后更新：2026-08-17

## 一、错误码 21 条（后端）

| # | msg_code | zh | en | vi | th |
|---|----------|----|----|----|----|
| 1 | INTERNAL_ERROR | 服务器内部错误，请稍后重试 | Internal server error. Please try again later. | Lỗi máy chủ nội bộ, vui lòng thử lại sau. | เกิดข้อผิดพลาดภายในเซิร์ฟเวอร์ กรุณาลองใหม่อีกครั้ง |
| 2 | PROXY_HOST_DENIED | 不允许代理该域名 | This domain is not allowed. | Không cho phép truy cập tên miền này. | ไม่อนุญาตให้เข้าถึงโดเมนนี้ |
| 3 | PROXY_FETCH_FAILED | 图片代理调用失败 | Failed to load image. | Không tải được hình ảnh. | โหลดรูปภาพไม่สำเร็จ |
| 4 | MISSING_AUTH | 缺少认证信息 | Authentication required. | Thiếu thông tin xác thực. | ไม่มีข้อมูลยืนยันตัวตน |
| 5 | TOKEN_INVALID | token 无效或已过期 | Your session has expired. Please log in again. | Phiên đăng nhập đã hết hạn. | เซสชันหมดอายุแล้ว |
| 6 | INVALID_LANG | 不支持的语言 | Language not supported. | Ngôn ngữ không được hỗ trợ. | ไม่รองรับภาษานี้ |
| 7 | LOGIN_REQUIRED | 请先登录 | Please log in first. | Vui lòng đăng nhập trước. | กรุณาเข้าสู่ระบบก่อน |
| 8 | HISTORY_NOT_FOUND | 记录不存在或无权操作 | Record not found or no permission. | Không tìm thấy bản ghi hoặc bạn không có quyền thao tác. | ไม่พบรายการ หรือคุณไม่มีสิทธิ์ดำเนินการ |
| 9 | OFFER_ID_INVALID | 商品 ID 格式不正确 | Invalid product ID. | Mã sản phẩm không hợp lệ. | รหัสสินค้าไม่ถูกต้อง |
| 10 | REPORT_NOT_FOUND | 报告未找到 | Report not found. | Không tìm thấy báo cáo. | ไม่พบรายงาน |
| 11 | REQUEST_VALIDATION_ERROR | 输入验证失败 | Invalid request. | Dữ liệu gửi lên không hợp lệ. | ข้อมูลที่ส่งมาไม่ถูกต้อง |
| 12 | OFFER_ID_NOT_FOUND | 无法从链接中提取有效的商品 ID | Could not extract a valid product ID from the link. | Không thể trích xuất mã sản phẩm từ liên kết. | ไม่สามารถดึงรหัสสินค้าจากลิงก์ได้ |
| 13 | GLOBAL_RATE_LIMIT | 系统繁忙，请稍后重试 | System is busy. Please try again later. | Hệ thống đang bận, vui lòng thử lại sau. | ระบบไม่ว่าง กรุณาลองใหม่อีกครั้ง |
| 14 | USER_NOT_FOUND | 用户不存在 | User not found. | Không tìm thấy người dùng. | ไม่พบผู้ใช้ |
| 15 | QUOTA_EXHAUSTED | 今日分析次数不足，请明天再试 | Daily analysis limit reached. Please try again tomorrow. | Đã hết số lần phân tích hôm nay, vui lòng thử lại vào ngày mai. | จำนวนครั้งในการวิเคราะห์วันนี้หมดแล้ว กรุณาลองใหม่พรุ่งนี้ |
| 16 | TASK_NOT_FOUND | 任务不存在 | Task not found. | Không tìm thấy tác vụ. | ไม่พบงานที่ร้องขอ |
| 17 | FETCH_FAILED_RETRY_TOMORROW | 该链接连续获取失败，请明天再试或联系 WhatsApp | This link keeps failing. Please try again tomorrow or contact us on WhatsApp. | Liên kết này liên tục lấy dữ liệu thất bại, vui lòng thử lại vào ngày mai hoặc liên hệ WhatsApp. | ลิงก์นี้ดึงข้อมูลไม่สำเร็จติดต่อกัน กรุณาลองใหม่พรุ่งนี้ หรือติดต่อ WhatsApp |
| 18 | APIFY_QUOTA_EXHAUSTED | 今日分析服务额度已用完，请明天再试 | Daily analysis quota used up. Please try again tomorrow. | Hạn mức dịch vụ phân tích hôm nay đã hết, vui lòng thử lại vào ngày mai. | โควตาบริการวิเคราะห์วันนี้หมดแล้ว กรุณาลองใหม่พรุ่งนี้ |
| 19 | TIMEOUT_RETRY | 获取超时，请稍后重试 | Request timed out. Please try again later. | Hết thời gian chờ lấy dữ liệu. Vui lòng thử lại sau. | หมดเวลาดึงข้อมูล กรุณาลองใหม่อีกครั้ง |
| 20 | FETCH_FAILED_RETRY_LATER | 获取失败，请稍后重试 | Failed to fetch. Please try again later. | Lấy dữ liệu thất bại, vui lòng thử lại sau. | ดึงข้อมูลไม่สำเร็จ กรุณาลองใหม่อีกครั้ง |
| 21 | PRODUCT_NOT_FOUND | 该链接可能已下架，请检查后重试 | This product may have been delisted. Please check and try again. | Sản phẩm có thể đã bị gỡ xuống, vui lòng kiểm tra và thử lại. | สินค้าอาจถูกนำออกแล้ว กรุณาตรวจสอบและลองใหม่ |

## 二、成功码（后端，前端不显示，无需翻译）

| msg_code | zh | 说明 |
|----------|----|------|
| OK | ok | 通用成功 |
| DELETE_OK | 已删除 | 删除成功 |

## 三、前端自发码（api.js / service-worker.js）

> 前端自己造、前端自己翻译的码，翻译同样在 `lang/*.json`。契约测试保证它们 4 语言都有翻译。

| msg_code | 来源 | zh | 说明 |
|----------|------|----|------|
| IPC_ERROR | api.js | 通信失败，请重载插件 | 消息通道通信失败 |
| EMPTY_RESPONSE | api.js | 空响应 | 后端无响应 |
| BODY_PARSE_FAILED | service-worker.js | 请求数据解析失败 | SW 解析消息体失败 |
| LOGIN_FAILED | service-worker.js | 登录失败 | Google 登录失败 |
| UNKNOWN_MSG_TYPE | service-worker.js | 未知的请求类型 | SW 收到未知消息类型 |
| OK | service-worker.js | 成功 | 登录成功 |

## 四、说明

- **th 为「推测」级**，上线前需泰国本地卖家复核。
- **#13 GLOBAL_RATE_LIMIT** 后端中文原文「系统繁忙不足」有语病（`InsufficientQuotaError` 拼 `{resource}不足` 所致），对照表用修正版「系统繁忙，请稍后重试」；后端待修。
- 后端 4 个异常默认值（`VALIDATION_ERROR` / `RESOURCE_NOT_FOUND` / `EXTERNAL_SERVICE_ERROR` / `INSUFFICIENT_QUOTA`）从不达前端（所有 raise 均显式传码），前端无对应 key，不在本表。

---

## 五、加减 msg 注意事项（必读）

> 病根：加/删 msg 码靠人 grep，漏了前端翻译、或删漏了 4 语言 key，没人报错。
> 兜底：`tests/test_msg_align.py` 是机器校验。加/删码后必跑 `pytest tests/test_msg_align.py`，不一致立刻红。
> ⚠️ 本表可能滞后，权威源 = 后端代码 + 前端 `lang/*.json` + 契约测试。

### 加一个新 msg 码 —— 4 步，缺一不可

| 步骤 | 动作 | 最容易漏的点 |
|------|------|-------------|
| 1 定名 | 全大写 `XXX_YYY`，语义明确 | 别用缩写/拼音 |
| 2 发出点 | 后端 `raise AppError(msg_code="X")` / `return {"msg_code":"X"}` / task dict `"error_msg_code":"X"` 三选一；或前端 `api.js` / `service-worker.js` 自发 | 前端自发码也是码，别漏 |
| 3 前端翻译 | `lang/{zh,en,vi,th}.json` **4 个文件同步加** `msg.XXX` | **最容易漏**，漏了用户看到裸码/英文 |
| 4 更新本表 + 跑测试 | 本表加一行 + `pytest tests/test_msg_align.py` | 测试红了 = 有漏 |

### 删一个 msg 码 —— 3 步

| 步骤 | 动作 | 最容易漏的点 |
|------|------|-------------|
| 1 后端删 | 删掉发出点 | — |
| 2 前端删 | **4 个语言 json 都删** `msg.XXX` | 只删 1 个语言 = 4 语言不对齐，测试红 |
| 3 更新本表 + 跑测试 | 本表删一行 + 跑契约测试 | — |

### 前端自发码（api.js / service-worker.js）

前端自己造的码（`IPC_ERROR` / `EMPTY_RESPONSE` / `LOGIN_FAILED` 等）**同样要 4 语言翻译**，别以为「后端没发就不用管」——它们是前端唯一翻译源。

### 机器兜底

`tests/test_msg_align.py` 扫三件事：

1. 后端「显式发出的码」⊆ 前端 4 语言 `msg.*` key
2. 前端自发码 ⊆ 前端 4 语言 `msg.*` key
3. `zh/en/vi/th` 四语言 `msg.*` key 集合完全一致

**加/删码后必跑，红了就是漏了。**

# msg_code 多语言对照表

> 后端 29 个 msg_code（26 错误 + 3 成功）→ 前端 4 语言文案。前端 i18n key = `msg.{CODE}`。
> 翻译归属：铁律九 层① 前端 i18n。改错误提示前先查此表。
> 权威源：后端 `routes/*.py` + `services/*.py` + `utils/exceptions.py` 的 msg_code 定义；前端 `src/chrome-ext/lang/*.json`。
> 最后更新：2026-08-15

## 一、错误码 26 条

| # | msg_code | zh | en | vi | th |
|---|----------|----|----|----|----|
| 1 | INTERNAL_ERROR | 服务器内部错误，请稍后重试 | Internal server error. Please try again later. | Lỗi máy chủ nội bộ, vui lòng thử lại sau. | เกิดข้อผิดพลาดภายในเซิร์ฟเวอร์ กรุณาลองใหม่อีกครั้ง |
| 2 | VALIDATION_ERROR | 输入验证失败 | Invalid input. | Dữ liệu nhập không hợp lệ. | ข้อมูลที่กรอกไม่ถูกต้อง |
| 3 | RESOURCE_NOT_FOUND | 资源不存在 | Resource not found. | Không tìm thấy dữ liệu. | ไม่พบข้อมูล |
| 4 | EXTERNAL_SERVICE_ERROR | 外部服务调用失败 | External service error. | Dịch vụ bên ngoài gặp sự cố. | บริการภายนอกขัดข้อง |
| 5 | INSUFFICIENT_QUOTA | 次数不足 | Usage limit reached. | Đã hết số lần sử dụng. | จำนวนครั้งไม่เพียงพอ |
| 6 | PROXY_HOST_DENIED | 不允许代理该域名 | This domain is not allowed. | Không cho phép truy cập tên miền này. | ไม่อนุญาตให้เข้าถึงโดเมนนี้ |
| 7 | PROXY_FETCH_FAILED | 图片代理调用失败 | Failed to load image. | Không tải được hình ảnh. | โหลดรูปภาพไม่สำเร็จ |
| 8 | MISSING_AUTH | 缺少认证信息 | Authentication required. | Thiếu thông tin xác thực. | ไม่มีข้อมูลยืนยันตัวตน |
| 9 | TOKEN_INVALID | token 无效或已过期 | Your session has expired. Please log in again. | Phiên đăng nhập đã hết hạn. | เซสชันหมดอายุแล้ว |
| 10 | INVALID_LANG | 不支持的语言 | Language not supported. | Ngôn ngữ không được hỗ trợ. | ไม่รองรับภาษานี้ |
| 11 | LOGIN_REQUIRED | 请先登录 | Please log in first. | Vui lòng đăng nhập trước. | กรุณาเข้าสู่ระบบก่อน |
| 12 | HISTORY_NOT_FOUND | 记录不存在或无权操作 | Record not found or no permission. | Không tìm thấy bản ghi hoặc bạn không có quyền thao tác. | ไม่พบรายการ หรือคุณไม่มีสิทธิ์ดำเนินการ |
| 13 | OFFER_ID_INVALID | 商品 ID 格式不正确 | Invalid product ID. | Mã sản phẩm không hợp lệ. | รหัสสินค้าไม่ถูกต้อง |
| 14 | REPORT_NOT_FOUND | 报告未找到 | Report not found. | Không tìm thấy báo cáo. | ไม่พบรายงาน |
| 15 | REQUEST_VALIDATION_ERROR | 输入验证失败 | Invalid request. | Dữ liệu gửi lên không hợp lệ. | ข้อมูลที่ส่งมาไม่ถูกต้อง |
| 16 | OFFER_ID_NOT_FOUND | 无法从链接中提取有效的商品 ID | Could not extract a valid product ID from the link. | Không thể trích xuất mã sản phẩm từ liên kết. | ไม่สามารถดึงรหัสสินค้าจากลิงก์ได้ |
| 17 | GLOBAL_RATE_LIMIT | 系统繁忙，请稍后重试 | System is busy. Please try again later. | Hệ thống đang bận, vui lòng thử lại sau. | ระบบไม่ว่าง กรุณาลองใหม่อีกครั้ง |
| 18 | USER_NOT_FOUND | 用户不存在 | User not found. | Không tìm thấy người dùng. | ไม่พบผู้ใช้ |
| 19 | QUOTA_EXHAUSTED | 今日分析次数不足，请明天再试 | Daily analysis limit reached. Please try again tomorrow. | Đã hết số lần phân tích hôm nay, vui lòng thử lại vào ngày mai. | จำนวนครั้งในการวิเคราะห์วันนี้หมดแล้ว กรุณาลองใหม่พรุ่งนี้ |
| 20 | TASK_NOT_FOUND | 任务不存在 | Task not found. | Không tìm thấy tác vụ. | ไม่พบงานที่ร้องขอ |
| 21 | ANALYSIS_EXPIRED | 分析已过期，请重新搜索该商品 | Analysis expired. Please search the product again. | Kết quả phân tích đã hết hạn, vui lòng tìm kiếm lại sản phẩm. | ผลการวิเคราะห์หมดอายุแล้ว กรุณาค้นหาสินค้าใหม่อีกครั้ง |
| 22 | SAVE_LIMIT_EXCEEDED | 已达保存上限，请先删除旧记录后再保存 | Save limit reached. Please delete old records first. | Đã đạt giới hạn lưu, vui lòng xóa bản ghi cũ trước khi lưu. | ถึงขีดจำกัดการบันทึกแล้ว กรุณาลบรายการเก่าก่อน |
| 23 | FETCH_FAILED_RETRY_TOMORROW | 该链接连续获取失败，请明天再试或联系 WhatsApp | This link keeps failing. Please try again tomorrow or contact us on WhatsApp. | Liên kết này liên tục lấy dữ liệu thất bại, vui lòng thử lại vào ngày mai hoặc liên hệ WhatsApp. | ลิงก์นี้ดึงข้อมูลไม่สำเร็จติดต่อกัน กรุณาลองใหม่พรุ่งนี้ หรือติดต่อ WhatsApp |
| 24 | APIFY_QUOTA_EXHAUSTED | 今日分析服务额度已用完，请明天再试 | Daily analysis quota used up. Please try again tomorrow. | Hạn mức dịch vụ phân tích hôm nay đã hết, vui lòng thử lại vào ngày mai. | โควตาบริการวิเคราะห์วันนี้หมดแล้ว กรุณาลองใหม่พรุ่งนี้ |
| 25 | FETCH_FAILED_RETRY_LATER | 获取失败，请稍后重试 | Failed to fetch. Please try again later. | Lấy dữ liệu thất bại, vui lòng thử lại sau. | ดึงข้อมูลไม่สำเร็จ กรุณาลองใหม่อีกครั้ง |
| 26 | PRODUCT_NOT_FOUND | 该链接可能已下架，请检查后重试 | This product may have been delisted. Please check and try again. | Sản phẩm có thể đã bị gỡ xuống, vui lòng kiểm tra và thử lại. | สินค้าอาจถูกนำออกแล้ว กรุณาตรวจสอบและลองใหม่ |

## 二、成功码（前端不显示，无需翻译）

| msg_code | zh | 说明 |
|----------|----|------|
| OK | ok | 通用成功 |
| DELETE_OK | 已删除 | 删除成功 |
| SAVE_OK | 已保存到我的分析 | 保存成功 |

## 三、说明

- **th 为「推测」级**，上线前需泰国本地卖家复核。
- **#17 GLOBAL_RATE_LIMIT** 后端中文原文「系统繁忙不足」有语病（`InsufficientQuotaError` 拼 `{resource}不足` 所致），对照表用修正版「系统繁忙，请稍后重试」；后端待修。
- **#2 与 #15** 中文相同（均「输入验证失败」），仅 code 不同（400 vs 422）。
- 前端内置 code（`NETWORK_ERROR` / `analyzeFailed` / `IPC_ERROR` 等）属层① UI 文案，不在本表。

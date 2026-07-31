// ===== Messages — 前端统一消息出口 =====
// 所有 Toast / 错误提示 / 成功提示走这一个文件。
// 使用：Messages.success("SAVE_OK") / Messages.handle(response) / Messages.warning("LOGIN_REQUIRED")
// 翻译：msg_code 对应 i18n JSON 中 msg.* key，前端只翻译这一个文件。
(function () {
  'use strict';

  function t(key, fallback) {
    return (typeof I18N !== 'undefined' && I18N.t) ? (I18N.t(key) || fallback) : fallback;
  }

  function show(code, fallback, type, sticky) {
    var text = t('msg.' + code, fallback);
    if (typeof Toast !== 'undefined') {
      if (type === 'error') Toast.error(text, sticky);
      else if (type === 'warning') Toast.warning(text, sticky);
      else if (type === 'success') Toast.success(text, sticky);
      else Toast.info(text, sticky);
    }
  }

  // ---- 公开 API ----

  /** 成功消息（自动消失） */
  function success(code, fallback) { show(code, fallback, 'success', false); }

  /** 警告消息（sticky，需点击关闭） */
  function warning(code, fallback) { show(code, fallback, 'warning', true); }

  /** 错误消息（sticky，需点击关闭） */
  function error(code, fallback) { show(code, fallback, 'error', true); }

  /** 信息消息（自动消失） */
  function info(code, fallback) { show(code, fallback, 'info', false); }

  /** 从 API 响应自动取 msg_code 并显示。成功消息自动消失，4xx 用 warning sticky，5xx 用 error sticky。 */
  function handle(resp) {
    if (!resp) return;
    var code = resp.msg_code;
    var message = resp.message || '';
    if (!code) return;
    if (code === 'OK' || code.slice(-3) === '_OK') {
      success(code, message);
    } else if (resp.code >= 500) {
      error(code, message);
    } else if (resp.code >= 400) {
      warning(code, message);
    }
  }

  window.Messages = {
    show: show,
    success: success,
    warning: warning,
    error: error,
    info: info,
    handle: handle
  };
})();

// ===== API 统一入口 =====
// 所有后端 API 调用走此文件。自动附带 JWT token，统一错误处理。
var API = (function () {
  'use strict';

  function authHeaders() {
    var headers = { 'Content-Type': 'application/json' };
    var token = getToken && getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return headers;
  }

  // ---- 统一错误处理（msg_code 驱动，委托给 Messages 统一显示） ----
  function _handleCommonErrors(data, httpStatus) {
    if (!data || typeof data !== 'object') return;
    var msgCode = data.msg_code;
    var message = data.message || '';

    // 403 配额不足 → 提示登录
    if (data.code === 403 && msgCode === 'DAILY_QUOTA_EXCEEDED') {
      Messages.warning(msgCode, message);
      return;
    }
    // 401 未登录
    if (data.code === 401) {
      Messages.warning(msgCode || 'LOGIN_REQUIRED', message);
      return;
    }
    // 5xx 服务器错误
    if (httpStatus >= 500) {
      Messages.error(msgCode || 'INTERNAL_ERROR', message);
    }
  }

  function analyze(url, lang) {
    return fetch('/api/analyze', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ url: url, lang: lang || '' })
    }).then(function (r) {
      return r.json().then(function (data) {
        _handleCommonErrors(data, r.status);
        return data;
      });
    });
  }

  function getTask(taskId) {
    return fetch('/api/analyze/' + taskId)
      .then(function (r) { return r.json(); });
  }

  function saveReport(offerId) {
    var token = getToken && getToken();
    return fetch('/api/save-report', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token
      },
      body: JSON.stringify({ offer_id: offerId })
    }).then(function (r) { return r.json(); });
  }

  function getHistory() {
    return fetch('/api/history', { headers: authHeaders() })
      .then(function (r) {
        return r.json().then(function (data) {
          _handleCommonErrors(data, r.status);
          return data;
        });
      });
  }

  function deleteHistory(id) {
    return fetch('/api/history/' + id, {
      method: 'DELETE',
      headers: authHeaders()
    }).then(function (r) {
      return r.json();
    });
  }

  function getReport(offerId, lang) {
    var url = '/api/report/' + offerId;
    if (lang) url += '?lang=' + encodeURIComponent(lang);
    return fetch(url, { headers: authHeaders() })
      .then(function (r) { return r.json(); });
  }

  function getConfig() {
    return fetch('/api/config')
      .then(function (r) { return r.json(); });
  }

  return {
    authHeaders: authHeaders,
    analyze: analyze,
    getTask: getTask,
    saveReport: saveReport,
    getHistory: getHistory,
    deleteHistory: deleteHistory,
    getReport: getReport,
    getConfig: getConfig
  };
})();

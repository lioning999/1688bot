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

  // ---- 统一错误提示（仅处理通用场景，页面可自行覆盖） ----
  function _handleCommonErrors(data, httpStatus) {
    if (!data || typeof data !== 'object') return;
    var msg = data.message || '';
    // 403 配额不足 → 提示登录
    if (data.code === 403 && msg.indexOf('次数') !== -1) {
      if (typeof Toast !== 'undefined') {
        Toast.warning(
          '今日免费分析次数不足 — ' +
          '<a href="/api/auth/google/login" style="color:var(--brand);font-weight:600">登录后可获更多次数 →</a>',
          true
        );
      }
      return;
    }
    // 401 未登录
    if (data.code === 401 && typeof Toast !== 'undefined') {
      Toast.info('请先登录后再操作', true);
      return;
    }
    // 5xx 服务器错误
    if (httpStatus >= 500 && typeof Toast !== 'undefined') {
      Toast.error('服务器繁忙，请稍后重试', true);
    }
  }

  function analyze(url) {
    return fetch('/api/analyze', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ url: url })
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

  function getReport(offerId) {
    return fetch('/api/report/' + offerId, { headers: authHeaders() })
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

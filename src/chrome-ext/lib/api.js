// ===== Sourcely — API 消息通道 =====
// MV3 标准：side panel 不发网络请求，所有 API 调用通过 sendMessage 委托给 service worker。

var API = (function () {
  'use strict';

  // 发送消息到 service-worker.js，返回 Promise
  function send(type, payload) {
    console.log('[API] send:', type, payload);
    return new Promise(function (resolve) {
      chrome.runtime.sendMessage({ type: type, payload: payload || {} }, function (res) {
        if (chrome.runtime.lastError) {
          console.error('[API] sendMessage error:', chrome.runtime.lastError.message);
          resolve({ code: 500, data: null, message: '通信失败，请重载插件', msg_code: 'IPC_ERROR' });
          return;
        }
        console.log('[API] recv:', type, res);
        // SW 返回就是标准 {code, data, message} 格式，直接透传
        resolve(res || { code: 500, data: null, message: '空响应', msg_code: 'EMPTY_RESPONSE' });
      });
    });
  }

  // ---- Token（side panel 本地缓存，加速 UI 判断登录态）----
  function getToken() {
    return sessionStorage.getItem('sourcely_token') || '';
  }

  function setToken(token) {
    sessionStorage.setItem('sourcely_token', token);
    chrome.storage.local.set({ sourcely_token: token });
  }

  function clearToken() {
    sessionStorage.removeItem('sourcely_token');
    chrome.storage.local.remove('sourcely_token');
  }

  function loadTokenFromStorage() {
    chrome.storage.local.get('sourcely_token', function (items) {
      if (items.sourcely_token) {
        sessionStorage.setItem('sourcely_token', items.sourcely_token);
      }
    });
  }

  // ---- API 端点 ----
  function analyze(url, lang) {
    return send('API_ANALYZE', { url: url, lang: lang || '' });
  }

  function getTask(taskId) {
    return send('API_GET_TASK', { taskId: taskId });
  }

  function getReport(offerId) {
    return send('API_GET_REPORT', { offerId: offerId });
  }

  function getHistory(page, limit) {
    return send('API_GET_HISTORY', { page: page || 1, limit: limit || 50 });
  }

  function toggleFavorite(id) {
    return send('API_TOGGLE_FAVORITE', { id: id });
  }

  function deleteHistory(id) {
    return send('API_DELETE_HISTORY', { id: id });
  }

  function getConfig() {
    return send('API_CONFIG', {});
  }

  function setLang(lang) {
    return send('SET_LANG', { lang: lang });
  }

  function getQuota() {
    return send('API_QUOTA', {});
  }

  function getCurrentTabUrl() {
    return send('GET_CURRENT_TAB_URL', {});
  }

  return {
    getToken: getToken,
    setToken: setToken,
    clearToken: clearToken,
    loadTokenFromStorage: loadTokenFromStorage,
    analyze: analyze,
    getTask: getTask,
    getReport: getReport,
    getHistory: getHistory,
    toggleFavorite: toggleFavorite,
    deleteHistory: deleteHistory,
    getConfig: getConfig,
    setLang: setLang,
    getQuota: getQuota,
    getCurrentTabUrl: getCurrentTabUrl
  };
})();

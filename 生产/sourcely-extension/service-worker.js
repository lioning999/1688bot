// ===== Sourcely Extension — Service Worker =====
// MV3 标准架构：唯一网络出口 + Badge + Token 管理。
// Side panel 不直接 fetch，通过 sendMessage 委托至此。

'use strict';

var API_BASE = 'https://sourcely1688.com';

// ---- Token（从 chrome.storage.local 读取，不信任 side panel 传参）----
function getStoredToken() {
  return new Promise(function (resolve) {
    chrome.storage.local.get('sourcely_token', function (items) {
      resolve(items.sourcely_token || '');
    });
  });
}

function authHeaders(token) {
  var h = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}

// ====================================================================
// API 代理 — 消息路由
// ====================================================================

function apiFetch(path, opts) {
  opts = opts || {};
  return fetch(API_BASE + path, opts).then(function (r) {
    return r.text().then(function (text) {
      try {
        return JSON.parse(text);
      } catch (e) {
        return { code: 500, data: null, message: text.slice(0, 200), msg_code: 'BODY_PARSE_FAILED' };
      }
    });
  });
}

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  var payload = msg.payload || {};

  function proxy(path, opts, needsAuth) {
    if (needsAuth === undefined) needsAuth = true;
    if (needsAuth) {
      return getStoredToken().then(function (token) {
        opts.headers = authHeaders(token);
        return apiFetch(path, opts);
      });
    }
    return apiFetch(path, opts);
  }

  switch (msg.type) {
    case 'API_ANALYZE':
      proxy('/api/analyze', { method: 'POST', body: JSON.stringify({ url: payload.url, lang: payload.lang || '' }) })
        .then(sendResponse);
      return true;

    case 'API_GET_TASK':
      proxy('/api/analyze/' + payload.taskId, { method: 'GET' }).then(sendResponse);
      return true;

    case 'API_GET_REPORT':
      proxy('/api/report/' + payload.offerId + '?lang=' + encodeURIComponent(payload.lang || ''), { method: 'GET' }).then(sendResponse);
      return true;

    case 'API_GET_HISTORY':
      proxy('/api/history?page=' + (payload.page || 1) + '&limit=' + (payload.limit || 50), { method: 'GET' }).then(sendResponse);
      return true;

    case 'API_DELETE_HISTORY':
      proxy('/api/history/' + payload.id, { method: 'DELETE' }).then(sendResponse);
      return true;

    case 'API_TOGGLE_FAVORITE':
      proxy('/api/history/favorite', { method: 'POST', body: JSON.stringify({ analysis_id: payload.id }) }).then(sendResponse);
      return true;

    case 'API_CONFIG':
      proxy('/api/config', { method: 'GET' }, false).then(sendResponse);
      return true;

    case 'API_QUOTA':
      getStoredToken().then(function (token) {
        console.log('[SW] API_QUOTA, has token:', !!token);
        return apiFetch('/api/quota', { headers: authHeaders(token) });
      }).then(function (data) {
        console.log('[SW] API_QUOTA response:', data);
        sendResponse(data);
      });
      return true;

    case 'LOGIN':
      // Google OAuth 登录 — 从 service worker 调用 launchWebAuthFlow（MV3 标准）
      // ⚠️ launchWebAuthFlow 必须在用户手势的同步调用栈触发，前面不能有 await/异步回调
      var extId = chrome.runtime.id;
      var currentLang = payload.lang || '';  // sidepanel 随消息传入，避免异步读 storage 丢手势
      var authUrl = API_BASE + '/api/auth/google/login?platform=extension&ext_id=' + extId;
      if (currentLang) authUrl += '&lang=' + currentLang;
      console.log('[SW] LOGIN: extId=' + extId + ' lang=' + currentLang);
      chrome.identity.launchWebAuthFlow({ url: authUrl, interactive: true }, function (redirectUrl) {
        console.log('[SW] LOGIN callback received, lastError=' + JSON.stringify(chrome.runtime.lastError));
        if (chrome.runtime.lastError || !redirectUrl) {
          console.error('[SW] LOGIN failed:', chrome.runtime.lastError);
          sendResponse({ code: 401, data: null, message: 'Login cancelled or failed', msg_code: 'LOGIN_FAILED' });
          return;
        }
        if (redirectUrl.indexOf('error=') !== -1) {
          console.error('[SW] LOGIN error in redirect:', redirectUrl);
          sendResponse({ code: 401, data: null, message: 'Login failed', msg_code: 'LOGIN_FAILED' });
          return;
        }
        var m = redirectUrl.match(/[?&]token=([^&]+)/);
        console.log('[SW] LOGIN token match:', m ? 'YES' : 'NO');
        if (m && m[1]) {
          var token = decodeURIComponent(m[1]);
          // 解码 JWT 提取 default_lang → 恢复语言（此处在回调内，已非手势路径，可异步）
          try {
            var jwtPayload = JSON.parse(atob(token.split('.')[1]));
            if (jwtPayload.default_lang) {
              chrome.storage.local.set({ sourcely_lang: jwtPayload.default_lang });
              console.log('[SW] LOGIN: restored lang=' + jwtPayload.default_lang + ' from JWT');
            }
          } catch (e) {
            console.log('[SW] LOGIN: JWT decode failed for lang restore, skipping');
          }
          chrome.storage.local.set({ sourcely_token: token }, function () {
            console.log('[SW] LOGIN success: token saved');
            sendResponse({ code: 200, data: { token: token }, message: 'ok', msg_code: 'OK' });
          });
        } else {
          console.error('[SW] LOGIN: no token in redirect URL');
          sendResponse({ code: 401, data: null, message: 'No token in redirect', msg_code: 'LOGIN_FAILED' });
        }
      });
      return true;

    case 'SET_LANG':
      // 用户切语言 → 异步同步后端，不阻塞
      getStoredToken().then(function (token) {
        return apiFetch('/api/user/lang', {
          method: 'PUT',
          headers: authHeaders(token),
          body: JSON.stringify({ lang: payload.lang })
        });
      }).then(function (data) {
        console.log('[SW] SET_LANG:', payload.lang, 'response:', data);
        sendResponse(data);
      });
      return true;

    case 'GET_CURRENT_TAB_URL':
      chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
        sendResponse({ url: tabs[0] ? tabs[0].url : null });
      });
      return true;

    default:
      sendResponse({ code: 400, data: null, message: 'Unknown message type', msg_code: 'UNKNOWN_MSG_TYPE' });
      return false;
  }
});

// ====================================================================
// Badge + Tab 监听
// ====================================================================

function setBadge(tabId, text, color) {
  if (!chrome.action) return;
  if (text !== undefined) {
    try { chrome.action.setBadgeText({ tabId: tabId, text: text }); } catch(e) {}
  }
  if (color !== undefined) {
    try { chrome.action.setBadgeBackgroundColor({ tabId: tabId, color: color }); } catch(e) {}
  }
}

function is1688Product(url) {
  if (!url) return false;
  return /1688\.com/.test(url) && /offer/i.test(url);
}

var pendingCheck = {};

function updateBadge(tabId, url) {
  if (!is1688Product(url)) { setBadge(tabId, '', '#000000'); return; }
  if (pendingCheck[tabId]) return;
  pendingCheck[tabId] = true;
  setBadge(tabId, '...', '#d97706');

  fetch(API_BASE + '/api/config', { method: 'GET' })
    .then(function () { setBadge(tabId, 'S', '#2563eb'); pendingCheck[tabId] = false; })
    .catch(function () { setBadge(tabId, 'S', '#2563eb'); pendingCheck[tabId] = false; });
}

chrome.tabs.onActivated.addListener(function (activeInfo) {
  chrome.tabs.get(activeInfo.tabId, function (tab) { updateBadge(activeInfo.tabId, tab.url); });
});

chrome.tabs.onUpdated.addListener(function (tabId, changeInfo, tab) {
  if (changeInfo.url || changeInfo.status === 'complete') updateBadge(tabId, tab.url);
});

chrome.action.onClicked.addListener(function (tab) {
  if (chrome.sidePanel) chrome.sidePanel.open({ windowId: tab.windowId });
});

if (chrome.sidePanel) {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(function () {});
}

chrome.runtime.onInstalled.addListener(function () {
  if (chrome.sidePanel) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(function () {});
  }
  chrome.storage.local.get('sourcely_lang', function (items) {
    if (!items.sourcely_lang) chrome.storage.local.set({ sourcely_lang: '' });
  });
});

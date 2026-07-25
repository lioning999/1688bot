// ===== Shared Nav + Footer + Google Auth =====
// Injects nav and footer into placeholder elements.

const NAV_LINKS = [
  { href: 'index.html',  label: '首页', key: 'index' },
  { href: 'history.html', label: '历史', key: 'history' },
];

var LANG_OPTS = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
  { value: 'vi', label: 'Tiếng Việt' },
  { value: 'th', label: 'ภาษาไทย' },
  { value: 'id', label: 'Bahasa Indonesia' },
];

// ===== Google Auth =====

function getToken() {
  return sessionStorage.getItem('accessToken');
}

function checkAuth() {
  var token = getToken();
  if (!token) return null;
  try {
    var payload = JSON.parse(atob(token.split('.')[1]));
    if (payload.exp * 1000 < Date.now()) {
      sessionStorage.removeItem('accessToken');
      sessionStorage.removeItem('user');
      return null;
    }
    var user = sessionStorage.getItem('user');
    if (user) return JSON.parse(user);
    // Bug #12：从 JWT payload 恢复用户信息（不再从 URL 读取）
    var derived = {
      email: payload.email || '',
      name: payload.name || '',
      avatar_url: payload.picture || ''
    };
    sessionStorage.setItem('user', JSON.stringify(derived));
    return derived;
  } catch (e) {
    return null;
  }
}

function initAuth() {
  // Handle post-login redirect: backend sends token via URL query（Bug #12：只传 token，用户信息从 JWT 解码）
  var params = new URLSearchParams(window.location.search);
  var token = params.get('token');
  if (token) {
    sessionStorage.setItem('accessToken', token);
    // 清除 URL 中的 token，保留其他参数（如 offerId）
    params.delete('token');
    var newSearch = params.toString();
    var newUrl = window.location.pathname + (newSearch ? '?' + newSearch : '');
    window.history.replaceState({}, document.title, newUrl);
  }
}

function logout() {
  sessionStorage.removeItem('accessToken');
  sessionStorage.removeItem('user');
  window.location.href = '/';
}

// Initialize auth on load
initAuth();

// ===== Toast 通知（全局可用） =====
var Toast = (function () {
  'use strict';

  var CONTAINER_ID = 'toastContainer';
  var DURATION = 4000;  // ms

  var ICONS = { error: '⚠️', success: '✅', warning: '⚠️', info: 'ℹ️' };

  function ensureContainer() {
    var el = document.getElementById(CONTAINER_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = CONTAINER_ID;
      el.className = 'toast-container';
      el.setAttribute('role', 'alert');
      el.setAttribute('aria-live', 'polite');
      document.body.appendChild(el);
    }
    return el;
  }

  function show(message, type, sticky) {
    type = type || 'info';
    sticky = !!sticky;
    var container = ensureContainer();
    var toast = document.createElement('div');
    toast.className = 'toast toast--' + type + (sticky ? ' toast--sticky' : '');

    var closeHtml = sticky ? '<button class="toast-close" aria-label="关闭">&times;</button>' : '';
    toast.innerHTML =
      '<span class="toast-icon">' + (ICONS[type] || '') + '</span>' +
      '<span class="toast-msg">' + String(message) + '</span>' + closeHtml;

    // Bug #17：限制同时最多 5 个 Toast
    while (container.children.length >= 5) {
      if (container.firstChild) container.removeChild(container.firstChild);
    }
    container.appendChild(toast);

    if (sticky) {
      // 点击关闭按钮
      var closeBtn = toast.querySelector('.toast-close');
      if (closeBtn) {
        closeBtn.addEventListener('click', function (e) { e.stopPropagation(); remove(toast); });
      }
      // 点击 toast 本身也关闭
      toast.style.cursor = 'pointer';
      toast.addEventListener('click', function () { remove(toast); });
    } else {
      // 自动消失
      var delay = type === 'error' ? 6000 : DURATION;
      setTimeout(function () { remove(toast); }, delay);
      // 点击提前关闭
      toast.style.cursor = 'pointer';
      toast.addEventListener('click', function () { remove(toast); });
    }
  }

  function remove(toast) {
    if (!toast || !toast.parentNode) return;
    toast.style.animation = 'toastOut .25s ease forwards';
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 260);
  }

  return {
    show: show,
    error:   function (msg, sticky) { show(msg, 'error', sticky); },
    success: function (msg, sticky) { show(msg, 'success', sticky); },
    warning: function (msg, sticky) { show(msg, 'warning', sticky); },
    info:    function (msg, sticky) { show(msg, 'info', sticky); }
  };
})();

// ===== Render =====

function renderNav(active) {
  var el = document.getElementById('appNav');
  if (!el) return;

  var user = checkAuth();

  // Auth area: login button or user avatar
  var authHtml;
  if (user) {
    var avatar = user.avatar_url || '';
    var name = user.name || user.email || '?';
    authHtml =
      '<div class="nav-user">' +
      '  <img src="' + avatar + '" class="nav-avatar" alt="' + name + '" title="' + name + '">' +
      '  <button class="nav-logout" onclick="logout()" title="退出登录" data-i18n="nav.logout">退出</button>' +
      '</div>';
  } else {
    authHtml =
      '<a href="/api/auth/google/login" class="nav-login-btn">' +
      '  <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>' +
      '  <span data-i18n="nav.login">登录</span>' +
      '</a>';
  }

  var linksHtml = NAV_LINKS.map(function(l) {
    var cls = l.key === active ? 'nav-link active' : 'nav-link';
    return '<a href="' + l.href + '" class="' + cls + '" data-i18n="nav.' + l.key + '">' + l.label + '</a>';
  }).join('\n        ');

  var langHtml = LANG_OPTS.map(function(o) {
    return '<option value="' + o.value + '">' + o.label + '</option>';
  }).join('\n          ');

  el.innerHTML =
    '<nav class="nav">\n' +
    '  <a href="index.html" style="text-decoration:none;">\n' +
    '    <div class="brand">\n' +
    '      <span class="brand-cn">源采</span>\n' +
    '      <span class="brand-en">SOURCELY</span>\n' +
    '    </div>\n' +
    '  </a>\n' +
    '  <div class="nav-links">\n        ' + linksHtml + '\n  </div>\n' +
    '  <select id="langSwitcher" class="lang-sw" aria-label="Language">\n          ' + langHtml + '\n  </select>\n' +
    '  ' + authHtml + '\n' +
    '</nav>';
}

function renderFooter() {
  var el = document.getElementById('appFooter');
  if (!el) return;
  el.innerHTML =
    '<footer class="app-footer">\n' +
    '  <div class="app-footer-brand">\n' +
    '    <span class="app-footer-logo">SOURCELY</span>\n' +
    '    <span class="app-footer-desc" data-i18n="footer.tagline">1688 源头工厂提供样品代采服务· 不用会中文 · 验货拍照 · 不满意可退</span>\n' +
    '  </div>\n' +
    '  <div class="app-footer-links">\n' +
    '    <a href="about.html" data-i18n="footer.about">关于我们</a>\n' +
    '    <a href="privacy.html" data-i18n="footer.privacy">隐私政策</a>\n' +
    '    <a href="terms.html" data-i18n="footer.terms">免责声明</a>\n' +
    '  </div>\n' +
    '  <p class="app-footer-copy" data-i18n="footer.copyright">&copy; 2024 Sourcely  义乌 · 中国</p>\n' +
    '</footer>\n' +
    '\n' +
    '<!-- WhatsApp Float -->\n' +
    '<a href="https://wa.me/8618561525786" class="wa-float" target="_blank" rel="noopener" aria-label="WhatsApp 咨询">\n' +
    '  <svg width="26" height="26" viewBox="0 0 24 24" fill="white"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.44 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>\n' +
    '</a>';
}

// 语言切换器事件委托（nav 是动态渲染的）
document.addEventListener('change', function (e) {
  if (e.target && e.target.id === 'langSwitcher') {
    var lang = e.target.value;
    if (typeof I18N !== 'undefined' && I18N.switchTo) {
      I18N.switchTo(lang);
    }
  }
});

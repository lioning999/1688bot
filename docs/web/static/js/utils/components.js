// ===== Shared Nav + Footer + Google Auth =====
// Injects nav and footer into placeholder elements.

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

const NAV_LINKS = [
  { href: '/index.html',  label: '首页', key: 'index' },
  { href: '/history.html', label: '历史', key: 'history' },
];

var LANG_OPTS = [
  { value: 'zh', label: '🇨🇳 ZH' },
  { value: 'en', label: '🇺🇸 EN' },
  { value: 'vi', label: '🇻🇳 VI' },
  { value: 'th', label: '🇹🇭 TH' },
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
  // Post-login: token 通过 cookie 传递（不再进 URL，防止被代理日志记录）
  var token = document.cookie.replace(/(?:(?:^|.*;\s*)sourcely_token\s*\=\s*([^;]*).*$)|^.*$/, '$1');
  if (token) {
    sessionStorage.setItem('accessToken', token);
    // 立即删除 cookie，完成一次性转存
    document.cookie = 'sourcely_token=; max-age=0; path=/; samesite=lax';
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
      '<span class="toast-msg">' + escHtml(String(message)) + '</span>' + closeHtml;

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
    var name = user.name || user.email || '?';
    authHtml =
      '<div class="nav-user">' +
      '  <button class="nav-logout" id="navLogoutBtn" title="退出登录" data-i18n="nav.logout">退出</button>' +
      '</div>';
  } else {
    authHtml =
      '<a href="/api/auth/google/login" class="nav-login-btn">' +
      '  <svg width="18" height="18" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>' +
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
    '  <a href="/index.html" style="text-decoration:none;">\n' +
    '    <div class="brand">\n' +
    '      <span class="brand-cn">SC</span>\n' +
    '    </div>\n' +
    '  </a>\n' +
    '  <div class="nav-links">\n        ' + linksHtml + '\n  </div>\n' +
    '  <select id="langSwitcher" class="lang-sw" aria-label="Language">\n          ' + langHtml + '\n  </select>\n' +
    '  ' + authHtml + '\n' +
    '</nav>';
  // Bind logout via event listener, not inline onclick
  var logoutBtn = el.querySelector('#navLogoutBtn');
  if (logoutBtn) logoutBtn.addEventListener('click', logout);

  // 静态页无 I18N 时，从 URL 路径设置语言切换器默认值
  if (typeof I18N === 'undefined' || !I18N.getLocale) {
    var m = window.location.pathname.match(/\/lang\/(\w+)\//);
    if (m) {
      var cur = (m[1] === 'cn') ? 'zh' : m[1];
      var sw = document.getElementById('langSwitcher');
      if (sw) sw.value = cur;
    }
  }
}

function renderFooter() {
  var el = document.getElementById('appFooter');
  if (!el) return;
  var locale = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() :
    ((window.location.pathname.match(/\/lang\/(\w+)\//) || [])[1] || 'zh');
  var langPath = (locale === 'zh') ? 'cn' : locale;
  el.innerHTML =
    '<footer class="app-footer">\n' +
    '  <div class="app-footer-brand">\n' +
    '    <span class="app-footer-logo">SOURCELY</span>\n' +
    '    <span class="app-footer-desc" data-i18n="footer.tagline">1688 源头工厂提供样品代采服务· 不用会中文 · 验货拍照 · 不满意可退</span>\n' +
    '  </div>\n' +
    '  <div class="app-footer-links">\n' +
    '    <a href="/lang/' + langPath + '/about.html" data-i18n="footer.about">关于我们</a>\n' +
    '    <a href="/lang/' + langPath + '/privacy.html" data-i18n="footer.privacy">隐私政策</a>\n' +
    '    <a href="/lang/' + langPath + '/terms.html" data-i18n="footer.terms">免责声明</a>\n' +
    '  </div>\n' +
    '  <p class="app-footer-copy" data-i18n="footer.copyright">&copy; Sourcely 义乌 · 中国</p>\n' +
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
    } else {
      // 静态页（无 i18n.js）：重定向到同页面的其他语言版本
      var path = window.location.pathname;
      var m = path.match(/\/lang\/\w+\/(.+)/);
      if (m) {
        var langDir = (lang === 'zh') ? 'cn' : lang;
        window.location.href = '/lang/' + langDir + '/' + m[1];
      }
    }
  }
});

// ===== Modal 确认/提示弹窗（统一风格，替代原生 confirm/alert） =====
var Modal = (function () {
  'use strict';

  var OVERLAY_ID = 'modalOverlay';
  var activeCallback = null;  // 当前弹窗的 onConfirm

  function t(key, fallback) {
    return (typeof I18N !== 'undefined' && I18N.t) ? (I18N.t(key) || fallback) : fallback;
  }

  function ensureOverlay() {
    var el = document.getElementById(OVERLAY_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = OVERLAY_ID;
      el.className = 'modal-overlay';
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-modal', 'true');
      el.addEventListener('click', function (e) {
        // 点击遮罩层关闭
        if (e.target === el) close();
      });
      document.body.appendChild(el);
    }
    return el;
  }

  function close() {
    var el = document.getElementById(OVERLAY_ID);
    if (el) {
      el.classList.remove('show');
      setTimeout(function () { el.innerHTML = ''; }, 200);
    }
    activeCallback = null;
  }

  function escapeHandler(e) {
    if (e.key === 'Escape') { close(); }
  }

  /**
   * confirm — 确认弹窗（替代原生 confirm()）
   * opts: { title, message, confirmText?, cancelText?, danger?, onConfirm }
   */
  function confirm(opts) {
    opts = opts || {};
    var title = opts.title || t('modal.confirmTitle', 'Confirm');
    var message = opts.message || '';
    var confirmText = opts.confirmText || t('modal.confirm', 'Confirm');
    var cancelText = opts.cancelText || t('modal.cancel', 'Cancel');
    var danger = !!opts.danger;
    var onConfirm = opts.onConfirm || null;

    var overlay = ensureOverlay();
    var confirmClass = danger ? 'modal-btn modal-btn-danger' : 'modal-btn modal-btn-primary';

    overlay.innerHTML =
      '<div class="modal-dialog">' +
      '  <div class="modal-header">' +
      '    <h3 class="modal-title">' + escHtml(title) + '</h3>' +
      '  </div>' +
      (message ? '  <div class="modal-body"><p class="modal-msg">' + escHtml(message) + '</p></div>' : '') +
      '  <div class="modal-footer">' +
      '    <button class="modal-btn modal-btn-cancel" id="modalCancelBtn">' + escHtml(cancelText) + '</button>' +
      '    <button class="' + confirmClass + '" id="modalConfirmBtn">' + confirmText + '</button>' +
      '  </div>' +
      '</div>';

    overlay.classList.add('show');

    // 绑定事件
    document.getElementById('modalCancelBtn').addEventListener('click', close);
    document.getElementById('modalConfirmBtn').addEventListener('click', function () {
      close();
      if (typeof onConfirm === 'function') onConfirm();
    });

    // ESC 关闭
    document.addEventListener('keydown', escapeHandler, { once: true });

    // 聚焦确认按钮
    setTimeout(function () {
      var btn = document.getElementById('modalConfirmBtn');
      if (btn) btn.focus();
    }, 100);
  }

  /**
   * alert — 提示弹窗（替代原生 alert()）
   * opts: { title, message, confirmText? }
   */
  function alert(opts) {
    opts = opts || {};
    var title = opts.title || '';
    var message = opts.message || '';
    var confirmText = opts.confirmText || t('modal.ok', 'OK');

    var overlay = ensureOverlay();

    overlay.innerHTML =
      '<div class="modal-dialog">' +
      '  <div class="modal-header">' +
      '    <h3 class="modal-title">' + escHtml(title) + '</h3>' +
      '  </div>' +
      (message ? '  <div class="modal-body"><p class="modal-msg">' + escHtml(message) + '</p></div>' : '') +
      '  <div class="modal-footer">' +
      '    <button class="modal-btn modal-btn-primary" id="modalConfirmBtn">' + escHtml(confirmText) + '</button>' +
      '  </div>' +
      '</div>';

    overlay.classList.add('show');

    document.getElementById('modalConfirmBtn').addEventListener('click', close);
    document.addEventListener('keydown', escapeHandler, { once: true });

    setTimeout(function () {
      var btn = document.getElementById('modalConfirmBtn');
      if (btn) btn.focus();
    }, 100);
  }

  return {
    confirm: confirm,
    alert: alert
  };
})();

// ===== 历史记录页 =====
// 登录用户查看/删除过往分析记录（只读 DB，不调 Apify）
(function () {
  'use strict';

  function t(key, fallback) {
    return (typeof I18N !== 'undefined' && I18N.t) ? (I18N.t(key) || fallback) : fallback;
  }

  var historyList = document.getElementById('historyList');
  var historyEmpty = document.getElementById('historyEmpty');
  var loginPrompt = document.getElementById('loginPrompt');
  var pageHint = document.getElementById('pageHint');

  // 汇率（从 /api/config 加载）
  var USD_RATE = 7.2;

  // lang → currency 映射
  var LANG_CURRENCY = { vi: 'VND', th: 'THB', id: 'IDR', en: 'USD', zh: 'USD' };
  var CURRENCY_SYMBOL = { VND: '₫', THB: '฿', IDR: 'Rp', USD: '$' };

  function formatLocalPrice(cny, lang) {
    var cur = LANG_CURRENCY[lang] || 'USD';
    if (cur === 'USD') return '$' + (cny / USD_RATE).toFixed(2);
    var rate = (I18N && I18N.RATES && I18N.RATES[cur]) || 1;
    var local = (cny / USD_RATE) * rate;
    var sym = CURRENCY_SYMBOL[cur] || '';
    if (cur === 'VND' || cur === 'IDR') {
      var rounded = Math.round(local / 1000) * 1000;
      return sym + rounded.toLocaleString('en-US');
    }
    return sym + local.toFixed(2);
  }

  // 加载汇率配置
  if (typeof API !== 'undefined' && API.getConfig) {
    API.getConfig().then(function (res) {
      if (res && res.data && res.data.cnyUsdRate) {
        USD_RATE = res.data.cnyUsdRate;
      }
    }).catch(function () {});
  }

  // ===== 加载历史 =====
  var user = checkAuth();
  if (!user) {
    loginPrompt.style.display = 'block';
    pageHint.textContent = t('history.loginHint', '登录后可查看历史分析记录');
  } else {
    loadHistory();
  }

  function loadHistory() {
    API.getHistory()
      .then(function(data) {
        if (data.code === 401) {
          loginPrompt.style.display = 'block';
          pageHint.textContent = t('history.sessionExpired', '登录已过期，请重新登录');
          return;
        }

        var items = (data.data && data.data.items) || [];
        if (!items.length) {
          historyEmpty.style.display = 'block';
          return;
        }

        historyList.style.display = 'block';
        pageHint.textContent = t('history.recordCount', '共 {n} 条记录').replace('{n}', items.length);
        renderItems(items);
      })
      .catch(function(err) {
        console.warn('History load failed:', err);
        pageHint.textContent = t('history.loadFailed', '加载失败，请刷新页面重试');
      });
  }

  function renderItems(items) {
    var html = '';
    items.forEach(function(item) {
      var cnyPrice = '';
      var localPrice = '';
      if (item.price_min != null) {
        cnyPrice = '¥' + item.price_min;
        if (item.price_max && item.price_max !== item.price_min) {
          cnyPrice += ' – ¥' + item.price_max;
        }
        // 本地货币换算价（基于分析时的语言）
        var lang = item.lang || 'zh';
        if (lang !== 'zh') {
          localPrice = ' <span class="hi-price-local">≈ ' + formatLocalPrice(item.price_min, lang) + '</span>';
        }
      }

      var sellerTag = '';
      if (item.seller_label) {
        sellerTag = '<span class="hi-tag">' + escapeHTML(item.seller_label) + '</span>';
      }

      var timeAgo = formatTimeAgo(item.created_at);
      var imgHtml = item.image_url
        ? '<img class="hi-thumb" src="' + escapeAttr(item.image_url) + '" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">'
        : '<div class="hi-thumb hi-thumb-empty"></div>';

      html +=
        '<div class="history-item" data-id="' + item.id + '">' +
          '<a href="report.html?offerId=' + escapeAttr(item.offer_id) + '" class="hi-link">' +
            imgHtml +
            '<div class="hi-body">' +
              '<div class="hi-title">' + escapeHTML(item.title || t('history.untitled', '(无标题)')) + '</div>' +
              '<div class="hi-meta">' +
                '<span class="hi-price">' + (cnyPrice || '—') + localPrice + '</span>' +
                sellerTag +
                '<span class="hi-time">' + timeAgo + '</span>' +
              '</div>' +
            '</div>' +
          '</a>' +
          '<button class="hi-del" data-id="' + item.id + '" data-offer-id="' + escapeAttr(item.offer_id || '') + '" title="' + t('history.delete', '删除') + '">×</button>' +
        '</div>';
    });
    historyList.innerHTML = html;

    var delBtns = historyList.querySelectorAll('.hi-del');
    delBtns.forEach(function(btn) {
      btn.addEventListener('click', onDelete);
    });
  }

  // ===== 删除 =====

  function onDelete(e) {
    e.preventDefault();
    e.stopPropagation();

    var btn = e.currentTarget;
    var id = parseInt(btn.getAttribute('data-id'), 10);
    if (!id) return;

    Modal.confirm({
      title: t('history.confirmDelete', 'Delete this record?'),
      confirmText: t('history.delete', 'Delete'),
      cancelText: t('modal.cancel', 'Cancel'),
      danger: true,
      onConfirm: function () { doDelete(btn, id); }
    });
  }

  function doDelete(btn, id) {
    var offerId = btn.getAttribute('data-offer-id') || '';
    btn.disabled = true;
    btn.textContent = '…';

    API.deleteHistory(id)
      .then(function(data) {
        if (data.code === 200) {
          // 清除保存标记，避免回 report 页时按钮灰色
          if (offerId) {
            sessionStorage.removeItem('saved_' + offerId);
          }

          var item = btn.closest('.history-item');
          if (item) item.remove();

          var remaining = historyList.querySelectorAll('.history-item').length;
          if (remaining === 0) {
            historyList.style.display = 'none';
            historyEmpty.style.display = 'block';
            pageHint.textContent = t('history.empty', '暂无分析记录');
          } else {
            pageHint.textContent = t('history.recordCount', '共 {n} 条记录').replace('{n}', remaining);
          }
        } else {
          btn.disabled = false;
          btn.textContent = '×';
          Messages.error('DELETE_FAILED', '删除失败，请稍后重试');
        }
      })
      .catch(function() {
        btn.disabled = false;
        btn.textContent = '×';
        Messages.error('NETWORK_ERROR', '网络错误，请稍后重试');
      });
  }

  // ===== 工具函数 =====

  function formatTimeAgo(dateStr) {
    if (!dateStr) return '';
    var now = Date.now();
    var then = new Date(dateStr.replace(' ', 'T') + (dateStr.indexOf('+') === -1 ? 'Z' : '')).getTime();
    if (isNaN(then)) return dateStr;
    var diff = Math.floor((now - then) / 1000);
    if (diff < 60) return t('time.justNow', '刚刚');
    if (diff < 3600) return Math.floor(diff / 60) + t('time.minutesAgo', ' 分钟前');
    if (diff < 86400) return Math.floor(diff / 3600) + t('time.hoursAgo', ' 小时前');
    if (diff < 604800) return Math.floor(diff / 86400) + t('time.daysAgo', ' 天前');
    return dateStr.slice(0, 10);
  }

  function escapeHTML(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
})();

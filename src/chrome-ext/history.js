// ===== Sourcely — 历史记录页 =====
// MV3 标准：通过 lib/api.js 委托所有网络请求。

var HistoryPage = (function () {
  'use strict';

  var _items = [];

  function getEls() {
    return {
      search: document.getElementById('historySearch'),
      list: document.getElementById('historyList'),
      counter: document.getElementById('historyCounter')
    };
  }

  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function formatTime(isoStr) {
    if (!isoStr) return '';
    var d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    var now = new Date();
    var diff = now - d;
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff/60000) + ' 分钟前';
    if (diff < 86400000) return Math.floor(diff/3600000) + ' 小时前';
    if (diff < 604800000) return Math.floor(diff/86400000) + ' 天前';
    return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
  }

  function load() {
    API.getHistory(1, 50).then(function (res) {
      if (!res || res.code !== 200) {
        var els = getEls();
        els.list.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><p>加载失败</p></div>';
        return;
      }
      _items = (res.data && res.data.items) ? res.data.items : [];
      renderList(_items);
    }).catch(function () {
      var els = getEls();
      els.list.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><p>加载失败</p></div>';
    });
  }

  function confirmDelete(item) {
    var overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = '<div class="confirm-dialog">' +
      '<p class="confirm-text">' + (I18N.t('history.deleteConfirm') || '确定删除这条记录？') + '</p>' +
      '<div class="confirm-actions">' +
        '<button class="confirm-btn confirm-btn-no">' + (I18N.t('history.cancel') || '取消') + '</button>' +
        '<button class="confirm-btn confirm-btn-yes">' + (I18N.t('history.delete') || '删除') + '</button>' +
      '</div></div>';
    document.body.appendChild(overlay);

    overlay.querySelector('.confirm-btn-no').addEventListener('click', function () {
      overlay.remove();
    });
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) overlay.remove();
    });

    overlay.querySelector('.confirm-btn-yes').addEventListener('click', function () {
      overlay.querySelector('.confirm-btn-yes').disabled = true;
      API.deleteHistory(item.analysis_id || item.id).then(function (res) {
        overlay.remove();
        if (res && res.code === 200) {
          load();
        } else {
          var els = getEls();
          els.list.insertAdjacentHTML('afterbegin',
            '<div class="empty-state" style="padding:12px;"><div class="empty-icon">⚠️</div><p>' +
            (I18N.t('msg.analyzeFailed') || '删除失败') + '</p></div>');
        }
      }).catch(function () {
        overlay.remove();
      });
    });
  }

  function renderList(items) {
    var els = getEls();
    if (!items || items.length === 0) {
      els.list.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><p>' +
        (I18N.t('history.empty') || '暂无历史记录') + '</p></div>';
      if (els.counter) els.counter.style.display = 'none';
      return;
    }

    // 计数器
    var total = String(items.length);
    var MAX = 20;  // TODO: 从后端 /api/quota 返回 history_max
    if (els.counter) {
      els.counter.style.display = 'block';
      els.counter.textContent = total + '/' + MAX;
      els.counter.className = 'history-counter' + (items.length >= MAX ? ' full' : '');
    }

    var html = '';
    items.forEach(function (item) {
      var thumb = item.image_url || '';
      var title = item.title || item.offer_id || '';
      var time = formatTime(item.created_at);
      var grade = item.seller_label ? (function () {
        var l = item.seller_label.toLowerCase();
        if (/超级|旗舰|实力|深度|sgs|tuv/i.test(l)) return 'go';
        if (/工厂|认证|实地/i.test(l)) return 'ok';
        return 'none';
      })() : 'none';
      var gradeEmoji = { go:'🟢', ok:'🟡', bad:'🔴', none:'⬜' };
      var favOn = item.favorited;

      html += '<div class="history-item" data-offer-id="' + escHtml(String(item.offer_id || '')) + '">';
      if (thumb) {
        html += '<img class="history-item-thumb" src="' + escHtml(thumb) +
                '" alt="" referrerpolicy="no-referrer" loading="lazy" onerror="this.style.display=\'none\'">';
      } else {
        html += '<div class="history-item-thumb" style="display:flex;align-items:center;justify-content:center;color:#9ca3af;">📦</div>';
      }
      html += '<div class="history-item-info">' +
              '<div class="history-item-title">' + escHtml(title) + '</div>' +
              '<div class="history-item-time">' + time + '</div>' +
              '</div>';
      html += '<span class="history-item-grade ' + grade + '">' + (gradeEmoji[grade] || '⬜') + '</span>';
      html += '<button class="history-item-fav' + (favOn ? ' on' : '') + '" data-id="' + escHtml(String(item.analysis_id || item.id || '')) + '" title="' + (I18N.t('history.favorite') || '收藏') + '">' + (favOn ? '⭐' : '☆') + '</button>';
      html += '<button class="history-item-del" data-id="' + escHtml(String(item.analysis_id || item.id || '')) + '" title="' + (I18N.t('history.delete') || '删除') + '">×</button>';
      html += '</div>';
    });

    // 上限提醒（≥18条时显示）
    if (items.length >= 18) {
      var left = MAX - items.length;
      html += '<div class="limit-warning">' +
        (left > 0
          ? '📌 还差 ' + left + ' 条就满了。<b>' + (I18N.t('history.favorite') || '收藏') + '</b>重要记录防止自动清除。'
          : '⚠️ 已达上限。新分析将自动清除最早的未收藏记录。<b>' + (I18N.t('history.favorite') || '收藏') + '</b>可防删。') +
        '</div>';
    }

    els.list.innerHTML = html;

    els.list.querySelectorAll('.history-item').forEach(function (el) {
      el.addEventListener('click', function () {
        var offerId = el.getAttribute('data-offer-id');
        if (offerId) switchToReport(offerId);
      });
    });

    // 收藏按钮 — 阻止冒泡防止触发 item 点击
    els.list.querySelectorAll('.history-item-fav').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var id = btn.getAttribute('data-id');
        API.toggleFavorite(parseInt(id, 10)).then(function (res) {
          if (res && res.code === 200 && res.data) {
            var newState = res.data.favorited;
            btn.textContent = newState ? '⭐' : '☆';
            btn.className = 'history-item-fav' + (newState ? ' on' : '');
          }
        });
      });
    });

    // 删除按钮 — 阻止冒泡防止触发 item 点击
    els.list.querySelectorAll('.history-item-del').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var id = btn.getAttribute('data-id');
        // 从 _items 中找到对应项
        var found = null;
        (_items || []).forEach(function (it) {
          if (String(it.analysis_id || it.id || '') === id) found = it;
        });
        if (found) confirmDelete(found);
      });
    });
  }

  function switchToReport(offerId) {
    document.querySelectorAll('.tab-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === 'report');
    });
    document.getElementById('tab-report').classList.add('active');
    document.getElementById('tab-history').classList.remove('active');

    API.getReport(offerId).then(function (res) {
      if (res && res.code === 200 && res.data && res.data.result) {
        if (typeof window._renderReport === 'function') {
          window._renderReport(res.data.result);
        }
      }
    });
  }

  function initSearch() {
    var els = getEls();
    if (!els.search) return;
    els.search.addEventListener('input', function () {
      var q = els.search.value.trim().toLowerCase();
      if (!q) { renderList(_items); return; }
      var filtered = _items.filter(function (item) {
        return (item.title || '').toLowerCase().indexOf(q) !== -1 ||
               (item.offer_id || '').toLowerCase().indexOf(q) !== -1;
      });
      renderList(filtered);
    });
  }

  function init() { initSearch(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  return { load: load, renderList: renderList };
})();

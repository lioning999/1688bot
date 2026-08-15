// ===== Sourcely — 历史记录页 =====
// MV3 标准：通过 lib/api.js 委托所有网络请求。

var HistoryPage = (function () {
  'use strict';

  var _items = [];
  var _selected = {};  // {offer_id: true} 对比勾选状态

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
    if (isNaN(d.getTime())) return '';
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
            (I18N.msg(res && res.msg_code, res && res.message) || '删除失败') + '</p></div>');
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

      var oid = String(item.offer_id || '');
      html += '<div class="history-item" data-offer-id="' + escHtml(oid) + '">';
      html += '<input type="checkbox" class="history-item-check" data-offer-id="' + escHtml(oid) + '"' + (_selected[oid] ? ' checked' : '') + '>';
      if (thumb) {
        html += '<img class="history-item-thumb" src="' + escHtml(thumb) +
                '" alt="" referrerpolicy="no-referrer" loading="lazy" onerror="this.style.display=\'none\'">';
      } else {
        html += '<div class="history-item-thumb" style="display:flex;align-items:center;justify-content:center;color:#9ca3af;">📦</div>';
      }
      html += '<div class="history-item-info">' +
              '<div class="history-item-title">' + escHtml(title) + '</div>' +
              '<div class="history-item-time">' + escHtml(time) + '</div>' +
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

    // 复选框 — 阻止冒泡（不触发 item 点击跳转报告）
    els.list.querySelectorAll('.history-item-check').forEach(function (cb) {
      cb.addEventListener('click', function (e) {
        e.stopPropagation();
        var oid = cb.getAttribute('data-offer-id');
        if (cb.checked) {
          // 最多 3 个
          var cnt = Object.keys(_selected).filter(function (k) { return _selected[k]; }).length;
          if (cnt >= 3) {
            cb.checked = false;
            showToast(I18N.t('compare.maxHint') || '最多选择 3 个商品进行对比', 'warning');
            return;
          }
          _selected[oid] = true;
        } else {
          _selected[oid] = false;
        }
        updateCompareBar();
      });
    });

    // item 点击 → 跳转报告（点复选框不触发）
    els.list.querySelectorAll('.history-item').forEach(function (el) {
      el.addEventListener('click', function (e) {
        // 不拦截复选框
        if (e.target.tagName === 'INPUT') return;
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

  // ====================================================================
  // 对比功能
  // ====================================================================

  function updateCompareBar() {
    var bar = document.getElementById('compareBar');
    var btn = document.getElementById('btnCompare');
    if (!bar || !btn) return;
    var ids = Object.keys(_selected).filter(function (k) { return _selected[k]; });
    if (ids.length >= 2) {
      bar.style.display = 'flex';
      btn.textContent = (I18N.t('compare.btn') || '对比') + ' (' + ids.length + ')';
      btn.disabled = false;
    } else {
      bar.style.display = 'none';
    }
  }

  function showToast(msg, type) {
    var t = document.createElement('div');
    t.className = 'toast ' + (type || '');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2000);
  }

  function showCompareModal(ids) {
    var modal = document.getElementById('compareModal');
    if (!modal) return;
    // 并行拉取 report
    var promises = ids.map(function (oid) {
      return API.getReport(oid).then(function (res) {
        if (res && res.code === 200 && res.data && res.data.result) {
          return { offerId: oid, display: res.data.result.display || res.data.result };
        }
        return { offerId: oid, display: null };
      }).catch(function () {
        return { offerId: oid, display: null };
      });
    });
    Promise.all(promises).then(function (results) {
      renderCompareTable(results);
      modal.style.display = 'flex';
    });
  }

  function hideCompareModal() {
    var modal = document.getElementById('compareModal');
    if (modal) modal.style.display = 'none';
  }

  function renderCompareTable(results) {
    var wrap = document.getElementById('compareTableWrap');
    if (!wrap) return;

    // 每行对比项：{label, extract(display)}
    var ROWS = [
      { label: I18N.t('compare.price') || '价格',    fn: function (d) { return d && d.price ? (d.price.low || 0) + '-' + (d.price.high || 0) : '-'; } },
      { label: I18N.t('compare.moq') || '起批',      fn: function (d) { return d && d.price && d.price.moq ? d.price.moq + ' 件' : '-'; } },
      { label: I18N.t('compare.product') || '产品评分', fn: function (d) { return d && d.productEval ? (d.productEval.grade || '') + ' ' + (d.productEval.score || 0) + '/' + (d.productEval.max_score || 18) : '-'; } },
      { label: '',                                     fn: function (d) { var s = d && d.summaryLine ? (d.summaryLine.short || '') : ''; return '<span class="cmp-verdict-short">' + escHtml(s) + '</span>'; }, isHtml: true },
      { label: I18N.t('compare.supplier') || '供应商评分', fn: function (d) { return d && d.supplierEval ? (d.supplierEval.grade || '') + ' ' + (d.supplierEval.score || 0) + '/' + (d.supplierEval.max_score || 9) : '-'; } },
      { label: '',                                     fn: function (d) { return _extractSupplierMeta(d); }, isHtml: true },
      { label: I18N.t('compare.sales') || '销量',      fn: function (d) { return d && d.sales && d.sales.sold ? d.sales.sold : '-'; } },
      { label: I18N.t('compare.repurchase') || '复购率', fn: function (d) { return _extractDim(d, 'repurchaseRate'); } }
    ];

    // 标题行
    var html = '<table class="compare-table"><thead><tr><th></th>';
    results.forEach(function (r) {
      var title = r.display && r.display.title ? r.display.title : r.offerId;
      html += '<th><div class="cmp-title" title="' + escHtml(title) + '">' + escHtml(String(title).slice(0, 16)) + '</div></th>';
    });
    html += '</tr></thead><tbody>';

    // 数据行
    ROWS.forEach(function (row, ri) {
      html += '<tr>';
      html += '<td>' + escHtml(row.label) + '</td>';
      results.forEach(function (r, ci) {
        var val = row.fn(r.display);
        if (row.isHtml) {
          html += '<td>' + val + '</td>';
        } else {
          html += '<td>' + escHtml(String(val)) + '</td>';
        }
      });
      html += '</tr>';
    });

    html += '</tbody></table>';
    wrap.innerHTML = html;
  }

  // 从 display 提取供应商身份标签（类型/认证/年限）
  function _extractSupplierMeta(d) {
    if (!d) return '<span class="cmp-identity">-</span>';
    var parts = [];
    // 身份类型
    var label = d.trustBar && d.trustBar.label ? d.trustBar.label : '';
    if (label) parts.push(label);
    // 认证 + 年限 从 supplierEval dimensions 取
    var dims = d.supplierEval && d.supplierEval.dimensions ? d.supplierEval.dimensions : [];
    dims.forEach(function (dim) {
      if (dim.key === 'd2' && dim.data) parts.push(dim.data);  // 认证
      if (dim.key === 'd3' && dim.data) parts.push(dim.data);  // 年限
    });
    var text = parts.length ? parts.join(' · ') : '-';
    return '<span class="cmp-identity">' + escHtml(text) + '</span>';
  }

  // 从 productEval dimensions 提取数值字段
  function _extractDim(d, field) {
    if (!d || !d.productEval || !d.productEval.dimensions) return '-';
    var found = null;
    d.productEval.dimensions.forEach(function (dim) {
      var data = dim.data || '';
      if (field === 'repurchaseRate' && data.indexOf('%') !== -1) found = data;
    });
    return found || '-';
  }

  function initCompare() {
    var bar = document.getElementById('compareBar');
    var btn = document.getElementById('btnCompare');
    var closeBtn = document.getElementById('compareCloseBtn');
    var backBtn = document.getElementById('compareBackBtn');

    if (btn) {
      btn.addEventListener('click', function () {
        var ids = Object.keys(_selected).filter(function (k) { return _selected[k]; });
        if (ids.length < 2) return;
        showCompareModal(ids);
      });
    }

    if (closeBtn) {
      closeBtn.addEventListener('click', hideCompareModal);
    }
    if (backBtn) {
      backBtn.addEventListener('click', hideCompareModal);
    }
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

  function init() { initSearch(); initCompare(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  return { load: load, renderList: renderList };
})();

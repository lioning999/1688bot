// ===== inspect.js — 1688 验货报告页渲染器 =====
// 依赖：api/core.js, utils/i18n.js, utils/components.js, utils/messages.js
// 数据源：display JSON（含 productEval / supplierEval / summaryLine）
(function () {
  'use strict';

  // ===== i18n 快捷方式 =====
  function t(key, fallback) {
    return (typeof I18N !== 'undefined' && I18N.t) ? (I18N.t(key) || fallback) : fallback;
  }

  // ===== 状态 =====
  var _display = null;       // 当前 display JSON
  var _samplePrice = 2.00;   // 拿样单价
  var _sampleMoq = 1;        // 起订量
  var _sampleQty = 2;        // 当前选择数量
  var _offerId = null;       // 当前 offer_id（用于保存）
  var _pollTimer = null;     // 轮询定时器引用

  // 费用常量
  var DOMESTIC_FEE = 10.00;   // 国内运费（CNY）
  var USD_RATE = 7.14;        // 汇率

  // ====================================================================
  // 入口
  // ====================================================================

  function init() {
    var params = new URLSearchParams(window.location.search);
    var sample = params.get('sample');
    var offerId = params.get('offerId');
    var url = params.get('url');
    var taskId = params.get('taskId');

    if (taskId) {
      startPolling(taskId);
    } else if (sample) {
      loadSample(sample);
    } else if (offerId) {
      loadFromCache(offerId);
    } else if (url) {
      startAnalysis(url);
    } else {
      // 尝试恢复上次未完成的轮询
      var lastTaskId = sessionStorage.getItem('lastTaskId');
      if (lastTaskId) {
        startPolling(lastTaskId);
      }
      // 不显示错误——可能正在从首页 redirect 过来
    }
  }

  // ====================================================================
  // 数据加载
  // ====================================================================

  function startAnalysis(url) {
    var lang = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() : '';
    API.analyze(url, lang)
      .then(function (data) {
        if (data.code !== 200) {
          hideSkeleton();
          return;
        }
        var taskId = data.data && data.data.task_id;
        if (!taskId) {
          hideSkeleton();
          return;
        }
        sessionStorage.setItem('lastTaskId', taskId);
        startPolling(taskId);
      })
      .catch(function (err) {
        hideSkeleton();
        console.warn('inspect: analyze start failed:', err);
      });
  }

  function startPolling(taskId) {
    pollTask(taskId, 0);
  }

  function pollTask(taskId, attempt) {
    if (attempt > 90) {
      hideSkeleton();
      sessionStorage.removeItem('lastTaskId');
      return;
    }

    API.getTask(taskId)
      .then(function (data) {
        var task = data.data;
        if (!task) {
          hideSkeleton();
          sessionStorage.removeItem('lastTaskId');
          return;
        }

        if (task.status === 'done') {
          sessionStorage.removeItem('lastTaskId');
          render(task.result);
          if (task.result && task.result.offerId) {
            cacheLastResult(task.result.offerId, task.result);
          }
          if (task.warning && typeof Messages !== 'undefined') {
            Messages.warning(task.warning_msg_code || 'STALE_DATA', task.warning);
          }
        } else if (task.status === 'failed') {
          hideSkeleton();
          sessionStorage.removeItem('lastTaskId');
        } else {
          // 仍在运行，2s 后重试
          _pollTimer = setTimeout(function () { pollTask(taskId, attempt + 1); }, 2000);
        }
      })
      .catch(function (err) {
        hideSkeleton();
        sessionStorage.removeItem('lastTaskId');
        console.warn('inspect: poll failed:', err);
      });
  }

  function loadSample(sampleName) {
    if (!/^[a-zA-Z0-9_-]+$/.test(sampleName)) {
      hideSkeleton();
      return;
    }

    var lang = (typeof I18N !== 'undefined' && I18N.getLocale && I18N.getLocale()) || 'en';
    if (['en', 'vi', 'th', 'id', 'zh'].indexOf(lang) === -1) lang = 'en';

    fetch('/samples/' + sampleName + '/display_' + lang + '.json')
      .then(function (r) { return r.json(); })
      .catch(function () {
        if (lang !== 'en') return fetch('/samples/' + sampleName + '/display_en.json').then(function (r) { return r.json(); });
        throw new Error('Sample not found');
      })
      .then(function (display) {
        render({ display: display || {} });
      })
      .catch(function () {
        hideSkeleton();
      });
  }

  function loadFromCache(offerId) {
    var key = 'lastResult_' + offerId;
    var cached = sessionStorage.getItem(key);
    if (cached) {
      try {
        var result = JSON.parse(cached);
        render(result);
        return;
      } catch (e) { /* ignore */ }
    }

    // 无缓存 → 调 API 获取已保存的报告
    var lang = (typeof I18N !== 'undefined' && I18N.getLocale && I18N.getLocale()) || '';
    API.getReport(offerId, lang)
      .then(function (data) {
        if (data.code === 200 && data.data) {
          render(data.data);
          cacheLastResult(offerId, data.data);
        } else {
          hideSkeleton();
        }
      })
      .catch(function () {
        hideSkeleton();
      });
  }

  function cacheLastResult(offerId, result) {
    try {
      sessionStorage.setItem('lastResult_' + offerId, JSON.stringify(result));
    } catch (e) { /* quota exceeded, ignore */ }
  }

  // ====================================================================
  // 主渲染
  // ====================================================================

  function render(result) {
    hideSkeleton();

    var d = result.display || {};
    _display = d;
    _offerId = d.offerId || (result.offerId) || null;

    // 提取价格参数
    var p = d.price || {};
    _samplePrice = p.low || 2;
    _sampleMoq = p.moq || 1;
    _sampleQty = _sampleMoq;

    renderProductCard(d);
    renderSummaryLine(d.summaryLine || {});
    renderProductEval(d.productEval || {}, d);
    renderSupplierEval(d.supplierEval || {}, d);
    renderSampleSection(d);

    // 显示内容区
    var content = document.getElementById('inspectContent');
    if (content) content.style.display = '';

    // 初始化保存栏
    initSaveBar();
  }

  // ====================================================================
  // 保存栏（Save + Share）
  // ====================================================================

  function initSaveBar() {
    var saveBar = document.getElementById('saveBar');
    var saveBtn = document.getElementById('saveBtn');
    if (!saveBar || !saveBtn) return;

    var token = (typeof getToken === 'function') ? getToken() : null;
    var loggedIn = !!token;

    saveBar.style.display = 'flex';

    if (!loggedIn) {
      saveBar.className = 'save-bar login-hint';
      saveBtn.textContent = '💾 Save';
      saveBtn.disabled = false;
      saveBtn.classList.remove('saved');
      saveBtn.onclick = function () {
        // 未登录 → 跳转 Google 登录
        var loginUrl = '/api/auth/google/login';
        sessionStorage.setItem('loginRedirect', window.location.href);
        window.location.href = loginUrl;
      };
      return;
    }

    saveBar.className = 'save-bar';
    saveBtn.textContent = '💾 Save';
    saveBtn.disabled = false;
    saveBtn.classList.remove('saved');
    saveBtn.onclick = function () {
      if (!_offerId) return;
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';
      API.saveReport(_offerId)
        .then(function (r) {
          if (r && r.code === 200) {
            saveBtn.textContent = '✓ Saved';
            saveBtn.classList.add('saved');
            saveBtn.onclick = null;
          } else {
            saveBtn.textContent = '💾 Save';
            saveBtn.disabled = false;
          }
        })
        .catch(function () {
          saveBtn.textContent = '💾 Save';
          saveBtn.disabled = false;
        });
    };
  }

  // ====================================================================
  // Card ① — 商品确认
  // ====================================================================

  function renderProductCard(d) {
    var p = d.price || {};

    // 主图
    var img = document.querySelector('.p01-img');
    if (img) {
      var src = (d.images && d.images[0]) ? d.images[0] : '';
      if (src) { img.src = src; }
    }

    // 标题
    var titleEl = document.querySelector('.p01-title');
    if (titleEl) titleEl.textContent = d.title || '';

    // 价格
    var priceEl = document.querySelector('.p01-price-hero b');
    if (priceEl) priceEl.textContent = (p.low || 0).toFixed(2);

    // 单位
    var unitEl = document.querySelector('.p01-unit');
    if (unitEl) unitEl.textContent = '/' + (p.unit || t('inspect.unit', 'piece'));

    // Meta 行：起订 / 月销 / 好评 / 排名 — 用 .p01-meta span:nth-child
    var metaSpans = document.querySelectorAll('.p01-meta span');
    if (metaSpans.length >= 2) {
      metaSpans[0].innerHTML = '📦 ' + t('inspect.moq', 'MOQ') + ' <b>' + (p.moq || '—') + '</b>';
    }
    // 月销来自 product_mapper.sold
    if (metaSpans.length >= 3 && d.sales && d.sales.sold) {
      metaSpans[1].innerHTML = '📊 ' + d.sales.sold;
    }
    // 好评率
    if (metaSpans.length >= 4) {
      var rateText = d.badges && d.badges.length ? '' : '—';
      metaSpans[2].innerHTML = rateText || '⭐ <b>—</b>';
      // 尝试从 badges 中找复购率显示
      if (d.badges && d.badges.length > 0) {
        for (var i = 0; i < d.badges.length; i++) {
          if (d.badges[i].text && d.badges[i].text.indexOf('%') !== -1) {
            metaSpans[2].innerHTML = '⭐ <b>' + d.badges[i].text + '</b>';
            break;
          }
        }
      }
      // 好评率优先
      if (d.productEval && d.productEval.dimensions) {
        var peDims = d.productEval.dimensions;
        for (var j = 0; j < peDims.length; j++) {
          if (peDims[j].key === 'd4') {
            metaSpans[2].innerHTML = '⭐ <b>' + (peDims[j].data || '—') + '</b>';
            break;
          }
        }
      }
    }
    // 排名
    if (metaSpans.length >= 4) {
      var rankText = (d.factory && d.factory.rankText) ? d.factory.rankText : '';
      metaSpans[3].innerHTML = rankText || '';
      metaSpans[3].style.display = rankText ? '' : 'none';
    }

    // 阶梯价格
    var tierEl = document.querySelector('.p01-tier');
    if (tierEl) {
      var tiers = d.priceTiers || [];
      if (tiers.length > 0) {
        var tierHtml = '';
        for (var k = 0; k < Math.min(tiers.length, 3); k++) {
          var t2 = tiers[k];
          var range = t2.qty_min != null ? (t2.qty_min + (t2.qty_max != null ? ('-' + t2.qty_max) : '+')) : '';
          tierHtml += '<span>' + range + '件 <b>¥' + (t2.unit_price != null ? Number(t2.unit_price).toFixed(2) : '—') + '</b></span>';
          if (k < Math.min(tiers.length, 3) - 1) tierHtml += '<span class="p01-tier-sep">│</span>';
        }
        tierEl.innerHTML = tierHtml;
      }
    }

    // 1688 链接
    var urlEl = document.querySelector('.p01-url');
    if (urlEl) {
      urlEl.href = d.itemUrl || '#';
      urlEl.style.display = d.itemUrl ? '' : 'none';
    }
  }

  // ====================================================================
  // Card ① — 综合结论
  // ====================================================================

  function renderSummaryLine(sl) {
    if (!sl) return;

    // 标题行
    var headlineEl = document.querySelector('.s2-headline');
    if (headlineEl && sl.headline) {
      headlineEl.textContent = sl.headline;

      // CSS class：根据 headline 内容推断
      headlineEl.classList.remove('go', 'ok', 'bad');
      if (sl.headline.indexOf('🟢') !== -1) headlineEl.classList.add('go');
      else if (sl.headline.indexOf('🟡') !== -1) headlineEl.classList.add('ok');
      else if (sl.headline.indexOf('🔴') !== -1) headlineEl.classList.add('bad');
    }

    // 理由
    var reasonEl = document.querySelector('.s2-reason');
    if (reasonEl && sl.reason) {
      reasonEl.textContent = sl.reason;
    }
  }

  // ====================================================================
  // Card ② — 产品验证
  // ====================================================================

  function renderProductEval(pe, d) {
    var group = document.querySelector('.eval-group');  // 第一个 eval-group
    if (!group) return;

    // --- 组头 ---
    var scoreEl = group.querySelector('.eval-group-score');
    if (scoreEl) {
      scoreEl.textContent = (pe.score != null ? pe.score : '—') + '/' + (pe.max_score || 15) + ' ' + t('inspect.scoreUnit', '分');
      scoreEl.classList.remove('go', 'ok', 'bad', 'none');
      scoreEl.classList.add(pe.grade || 'none');
    }

    var descEl = group.querySelector('.eval-group-desc');
    if (descEl) {
      descEl.textContent = pe.summary || '';
    }

    // --- 组体 ---
    var bodyEl = group.querySelector('.eval-group-body');
    if (!bodyEl) return;

    var dims = pe.dimensions || [];
    var html = '';

    // 维度行
    for (var i = 0; i < dims.length; i++) {
      var dim = dims[i];
      var label = (dim.label || dim.icon + ' ' + dim.name || '').trim();
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">' + escHtml(label) + '</span>' +
        '<span class="eval-dim-data">' + escHtml(dim.data || '') + '</span>' +
        '<span class="eval-dim-ref">' + escHtml(dim.ref || '') + '</span>' +
        '</div>';
    }

    // 补充信息：排名
    if (d.factory && d.factory.rankText) {
      html += '<div class="eval-extra">🏆 ' + escHtml(d.factory.rankText) + '</div>';
    }

    // 补充信息：库存（display JSON 已含翻译文本 + 档位）
    var stockLevel = pe.stockLevel;
    if (stockLevel) {
      var stockClass = stockLevel.level === 'ok' ? 'inv-ok' : 'inv-warn';
      html += '<div class="eval-extra ' + stockClass + '">📦 ' + escHtml(stockLevel.text) + '</div>';
    }

    // 人话判词
    if (pe.verdict) {
      html += '<div class="eval-human ' + (pe.grade || 'none') + '">💬 ' + escHtml(pe.verdict) + '</div>';
    }

    bodyEl.innerHTML = html;
  }

  // ====================================================================
  // Card ② — 供应商验证
  // ====================================================================

  function renderSupplierEval(se, d) {
    var groups = document.querySelectorAll('.eval-group');
    if (groups.length < 2) return;
    var group = groups[1];  // 第二个 eval-group

    // --- 组头 ---
    var scoreEl = group.querySelector('.eval-group-score');
    if (scoreEl) {
      scoreEl.textContent = (se.score != null ? se.score : '—') + '/' + (se.max_score || 9) + ' ' + t('inspect.scoreUnit', '分');
      scoreEl.classList.remove('go', 'ok', 'bad', 'none');
      scoreEl.classList.add(se.grade || 'none');
    }

    var descEl = group.querySelector('.eval-group-desc');
    if (descEl) {
      descEl.textContent = se.summary || '';
    }

    // --- 组体 ---
    var bodyEl = group.querySelector('.eval-group-body');
    if (!bodyEl) return;

    var dims = se.dimensions || [];
    var html = '';

    // 维度行
    for (var i = 0; i < dims.length; i++) {
      var dim = dims[i];
      var label = (dim.label || dim.icon + ' ' + dim.name || '').trim();
      var helpHtml = '';
      // D1 身份 / D2 认证 — 加 ？帮助按钮
      if (i < 2) {
        helpHtml = ' <span class="eval-help" onclick="InspectPage.toggleHelp(this)">？</span>';
      }
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">' + escHtml(label) + helpHtml + '</span>' +
        '<span class="eval-dim-data">' + escHtml(dim.data || '') + '</span>' +
        '<span class="eval-dim-ref">' + escHtml(dim.ref || '') + '</span>' +
        '</div>';

      // D1 帮助文本
      if (i === 0 && dim.data_key === '实力商家') {
        html += '<div class="eval-help-text">' + escHtml(se.helpTexts.verified || '') + '</div>';
      }
      // D2 帮助文本
      if (i === 1) {
        if (dim.data_key === 'supp_dim_d2_data_no_cert') {
          html += '<div class="eval-help-text">' + escHtml(se.helpTexts.noCert || '') + '</div>';
          html += '<div class="eval-risk-note">⚠️ ' + escHtml(se.helpTexts.riskNoCert || '') + '</div>';
        }
      }
    }

    // 附加信息：公司名称
    var companyName = se.companyName || (d.factory && d.factory.supplierName) || '';
    if (companyName) {
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">🏢 ' + t('inspect.companyName', '公司名称') + ' <span class="eval-help" onclick="InspectPage.toggleHelp(this)">？</span></span>' +
        '<span class="eval-dim-data">' + escHtml(companyName) + '</span>' +
        '<span class="eval-dim-ref"></span>' +
        '</div>';
      html += '<div class="eval-help-text">' + escHtml((d.factory && d.factory.companyNameExplain) || '') + '</div>';
    }

    // 附加信息：产业带
    var cluster = se.industryCluster || '';
    if (cluster) {
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">📍 ' + t('inspect.industryCluster', '产业带') + ' <span class="eval-help" onclick="InspectPage.toggleHelp(this)">？</span></span>' +
        '<span class="eval-dim-data">' + escHtml(cluster) + '</span>' +
        '<span class="eval-dim-ref"></span>' +
        '</div>';
      html += '<div class="eval-help-text">' + escHtml((d.factory && d.factory.industryExplain) || '') + '</div>';
    }

    // 人话判词
    if (se.verdict) {
      var gradeClass = se.grade || 'none';
      html += '<div class="eval-human ' + gradeClass + '">💬 ' + escHtml(se.verdict) + '</div>';
    }

    bodyEl.innerHTML = html;
  }

  // ====================================================================
  // Card ③ — 拿样验货
  // ====================================================================

  function renderSampleSection(d) {
    var p = d.price || {};

    // 数量控制
    document.getElementById('qtyVal').textContent = _sampleQty;
    document.getElementById('qtyMinus').disabled = (_sampleQty <= _sampleMoq);

    // 数量按钮事件
    document.getElementById('qtyMinus').onclick = function () {
      if (_sampleQty > _sampleMoq) { _sampleQty--; updateCost(); }
    };
    document.getElementById('qtyPlus').onclick = function () {
      if (_sampleQty < 50) { _sampleQty++; updateCost(); }
    };

    // 起订提示（i18n 格式串：{n} 替换为实际 MOQ）
    var moqHint = document.getElementById('moqHint');
    if (moqHint) {
      moqHint.textContent = t('inspect.moqLabel', 'MOQ {n} pcs').replace('{n}', _sampleMoq);
    }

    updateCost();
  }

  // ====================================================================
  // 费用计算
  // ====================================================================

  function updateCost() {
    document.getElementById('qtyVal').textContent = _sampleQty;
    document.getElementById('qtyMinus').disabled = (_sampleQty <= _sampleMoq);

    var productCny = _samplePrice * _sampleQty;
    var depositCny = productCny + DOMESTIC_FEE;

    // 定金行
    var depositEl = document.getElementById('depositTotal');
    if (depositEl) {
      depositEl.textContent = '¥' + depositCny.toFixed(2);
    }

    // 商品小计
    var feeQtySmall = document.getElementById('feeQtySmall');
    if (feeQtySmall) feeQtySmall.textContent = _samplePrice.toFixed(2);
    var feeQty = document.getElementById('feeQty');
    if (feeQty) feeQty.textContent = _sampleQty;

    // 合计
    var shipLow = 3, shipHigh = 5;
    var totalLow = depositCny / USD_RATE + shipLow + 10;
    var totalHigh = depositCny / USD_RATE + shipHigh + 10;
    var totalEl = document.getElementById('totalFee');
    if (totalEl) {
      totalEl.textContent = '$' + Math.round(totalLow) + ' – $' + Math.round(totalHigh);
    }
  }

  // ====================================================================
  // 交互
  // ====================================================================

  // 折叠组切换
  function toggleGroup(header) {
    header.parentElement.classList.toggle('open');
  }

  // 帮助文本切换
  function toggleHelp(el) {
    var dim = el.closest('.eval-dim');
    var text = dim.nextElementSibling;
    if (text && text.classList.contains('eval-help-text')) {
      text.classList.toggle('open');
    }
  }

  // 验货实拍折叠
  function toggleInspect() {
    var section = document.querySelector('.inspect-section');
    if (section) section.classList.toggle('open');
  }

  // ====================================================================
  // 保存功能
  // ====================================================================

  function saveReport() {
    if (!_offerId) return;

    if (typeof API === 'undefined' || !API.saveReport) {
      console.warn('inspect: API.saveReport not available');
      return;
    }

    var btn = document.getElementById('saveBtn');
    if (btn) { btn.disabled = true; btn.textContent = t('report.savingBtn', 'Saving...'); }

    API.saveReport(_offerId)
      .then(function (data) {
        if (data.code === 200) {
          sessionStorage.setItem('saved_' + _offerId, '1');
          if (btn) { btn.textContent = t('report.savedBtn', '✓ Saved'); btn.classList.add('saved'); }
          if (typeof Messages !== 'undefined') Messages.success('SAVE_OK', 'Saved!');
        } else {
          if (btn) { btn.disabled = false; btn.textContent = t('report.saveBtn', '💾 Save'); }
        }
      })
      .catch(function () {
        if (btn) { btn.disabled = false; btn.textContent = t('report.saveBtn', '💾 Save'); }
      });
  }

  // ====================================================================
  // 骨架屏
  // ====================================================================

  function hideSkeleton() {
    var skel = document.getElementById('skeleton');
    if (skel) skel.style.display = 'none';
  }

  // ====================================================================
  // 工具函数
  // ====================================================================

  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ====================================================================
  // 公开 API
  // ====================================================================

  window.InspectPage = {
    init: init,
    render: render,
    toggleGroup: toggleGroup,
    toggleHelp: toggleHelp,
    toggleInspect: toggleInspect,
    updateCost: updateCost,
    saveReport: saveReport,
  };

  // ====================================================================
  // 页面启动
  // ====================================================================
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

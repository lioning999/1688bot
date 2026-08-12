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
  var _searching = false;    // 搜索防抖标志（铁律：所有入口设 true，resetSearchBtn 恢复）

  // 费用常量
  var DOMESTIC_FEE = 10.00;   // 国内运费（CNY）
  var SERVICE_FEE = 10.00;    // 服务费（USD）
  var USD_RATE = 7.14;        // 汇率（默认值，init 时从 /api/config 更新）

  // 国际运费表 — 按国家（语言→国家→陆运/空运价格区间 USD）
  var shipRates = {
    VN: { eco: [3, 5],  label: '🚛 陆运', days: '4-7天', exp: [7, 12], expLabel: '✈️ 空运', expDays: '2-3天' },
    TH: { eco: [5, 8],  label: '🚛 陆运', days: '5-7天', exp: [8, 15], expLabel: '✈️ 空运', expDays: '3-5天' },
    ID: { eco: [10, 18], label: '✈️ 空运', days: '5-10天', exp: null, expLabel: null, expDays: null },
    MY: { eco: [5, 8],  label: '🚛 陆运', days: '5-7天', exp: [8, 14], expLabel: '✈️ 空运', expDays: '3-5天' },
    PH: { eco: [10, 16], label: '✈️ 空运', days: '7-10天', exp: null, expLabel: null, expDays: null }
  };
  var DEST_MAP = { vi: 'VN', th: 'TH', id: 'ID' };

  // CNY → 本地货币换算（用于价格展示）
  var LANG_CURRENCY = { vi: 'VND', th: 'THB', id: 'IDR', en: 'USD', zh: 'USD' };
  var CURRENCY_SYMBOL = { VND: '₫', THB: '฿', IDR: 'Rp', USD: '$' };
  function _formatLocalPrice(cny) {
    if (!cny) return '';
    var lang = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() : '';
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

  // 防抖入口：设 _searching + 禁用搜索按钮 + 显示骨架屏（铁律：所有程序化入口必须调用）
  function _enterSearching(hintText) {
    _searching = true;
    var btn = document.getElementById('searchBtn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = t('search.analyzing', '分析中...');
    }
    var hint = document.querySelector('.search-hint');
    if (hint) hint.textContent = hintText || t('search.analyzing', '分析中...');
    // 显示骨架屏，隐藏内容和错误
    var content = document.getElementById('inspectContent');
    var error = document.getElementById('inspectError');
    var skel = document.getElementById('skeleton');
    if (content) content.style.display = 'none';
    if (error) error.style.display = 'none';
    if (skel) skel.style.display = '';
  }

  // ====================================================================
  // 入口
  // ====================================================================

  function init() {
    // 从 /api/config 加载最新汇率（独立于 i18n.js）
    if (typeof API !== 'undefined' && API.getConfig) {
      API.getConfig().then(function (res) {
        if (res && res.data && res.data.cnyUsdRate) {
          USD_RATE = res.data.cnyUsdRate;
          updateCost();
        }
      }).catch(function () { /* 保持默认值 */ });
    }

    var params = new URLSearchParams(window.location.search);
    var sample = params.get('sample');
    var offerId = params.get('offerId');
    var url = params.get('url');
    var taskId = params.get('taskId');

    if (taskId) {
      _enterSearching(t('search.analyzing', '分析中...'));
      startPolling(taskId);
    } else if (sample) {
      _enterSearching(t('report.sampleLoading', 'Loading sample data...'));
      loadSample(sample);
    } else if (offerId) {
      _enterSearching(t('report.dbLoadingHint', 'Loading saved analysis...'));
      loadFromCache(offerId);
    } else if (url) {
      _enterSearching(t('search.analyzing', '分析中...'));
      startAnalysis(url);
    } else {
      // 尝试恢复上次未完成的轮询
      var lastTaskId = sessionStorage.getItem('lastTaskId');
      if (lastTaskId) {
        _enterSearching(t('report.resuming', 'Resuming unfinished analysis...'));
        startPolling(lastTaskId);
      }
      // 不显示错误——可能正在从首页 redirect 过来
    }

    setupSearch();
  }

  // ====================================================================
  // 数据加载
  // ====================================================================

  function startAnalysis(url) {
    var lang = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() : '';
    API.analyze(url, lang)
      .then(function (data) {
        if (data.code !== 200) {
          // API 层已统一弹 Toast（403配额/401未登录/5xx）
          // 这里只更新页面状态，不重复弹 Toast
          var hint = document.querySelector('.search-hint');
          resetSearchBtn();
          if (hint) {
            hint.textContent = data.message || t('report.startFailed', '分析启动失败');
            hint.style.color = 'var(--seal)';
            setTimeout(function () {
              hint.textContent = t('search.hint', '每日免费 3 次 · 登陆后10次/日');
              hint.style.color = '';
            }, 5000);
          }
          hideSkeleton();
          return;
        }
        var taskId = data.data && data.data.task_id;
        if (!taskId || typeof taskId !== 'string') {
          resetSearchBtn();
          hideSkeleton();
          if (typeof Messages !== 'undefined') {
            Messages.error('ANALYSIS_FAILED', '分析启动失败，请稍后重试');
          }
          return;
        }
        sessionStorage.setItem('lastTaskId', taskId);
        startPolling(taskId);
      })
      .catch(function (err) {
        resetSearchBtn();
        hideSkeleton();
        if (typeof Messages !== 'undefined') {
          Messages.error('NETWORK_ERROR', '网络错误，请检查网络后重试');
        }
        console.warn('inspect: analyze start failed:', err);
      });
  }

  function startPolling(taskId) {
    pollTask(taskId, 0);
  }

  function pollTask(taskId, attempt) {
    if (attempt > 60) {
      resetSearchBtn();
      hideSkeleton();
      sessionStorage.removeItem('lastTaskId');
      if (typeof Messages !== 'undefined') {
        Messages.error('ANALYSIS_TIMEOUT', '分析超时，请稍后重试');
      }
      return;
    }

    API.getTask(taskId)
      .then(function (data) {
        var task = data.data;
        if (!task) {
          resetSearchBtn();
          hideSkeleton();
          sessionStorage.removeItem('lastTaskId');
          if (typeof Messages !== 'undefined') {
            Messages.error('TASK_EXPIRED', '任务不存在或已过期');
          }
          return;
        }

        if (task.status === 'done') {
          resetSearchBtn();
          // 更新 searchHint 为正常文案
          var hint = document.querySelector('.search-hint');
          if (hint) {
            hint.textContent = t('search.hint', '每日免费 3 次 · 登陆后10次/日');
            hint.style.color = '';
          }
          sessionStorage.removeItem('lastTaskId');
          render(task.result);
          if (task.result && task.result.offerId) {
            cacheLastResult(task.result.offerId, task.result);
          }
          if (task.warning && typeof Messages !== 'undefined') {
            Messages.warning(task.warning_msg_code || 'STALE_DATA', task.warning);
          }
        } else if (task.status === 'failed') {
          resetSearchBtn();
          hideSkeleton();
          sessionStorage.removeItem('lastTaskId');
          if (typeof Messages !== 'undefined') {
            Messages.error(task.error_msg_code || 'ANALYSIS_FAILED', task.error || '分析失败，请稍后重试');
          }
        } else {
          // 仍在运行，2s 后重试
          _pollTimer = setTimeout(function () { pollTask(taskId, attempt + 1); }, 2000);
        }
      })
      .catch(function (err) {
        resetSearchBtn();
        hideSkeleton();
        sessionStorage.removeItem('lastTaskId');
        if (typeof Messages !== 'undefined') {
          Messages.error('NETWORK_ERROR', '网络错误，请检查网络后重试');
        }
        console.warn('inspect: poll failed:', err);
      });
  }

  function loadSample(sampleName) {
    if (!/^[a-zA-Z0-9_-]+$/.test(sampleName)) {
      showInspectError();
      return;
    }

    // 显示加载态
    var hint = document.querySelector('.search-hint');
    if (hint) hint.textContent = t('report.sampleLoading', 'Loading sample data...');

    var lang = (typeof I18N !== 'undefined' && I18N.getLocale && I18N.getLocale()) || 'en';
    if (['en', 'vi', 'th', 'zh'].indexOf(lang) === -1) lang = 'en';

    fetch('/samples/' + sampleName + '/display_' + lang + '.json')
      .then(function (r) { return r.json(); })
      .catch(function () {
        if (lang !== 'en') return fetch('/samples/' + sampleName + '/display_en.json').then(function (r) { return r.json(); });
        throw new Error('Sample not found');
      })
      .then(function (display) {
        var d = display || {};
        render({ display: d });
        // 样例加载后填充搜索框
        var input = document.getElementById('searchInput');
        if (input && d.itemUrl) input.value = d.itemUrl;
        if (hint) {
          hint.textContent = t('search.hint', '每日免费 3 次 · 登陆后10次/日');
          hint.style.color = '';
        }
      })
      .catch(function () {
        resetSearchBtn();
        hideSkeleton();
        if (hint) hint.textContent = t('report.sampleFailed', 'Sample failed to load, paste a link to search');
      });
  }

  function loadFromCache(offerId) {
    // 1. sessionStorage 缓存 → 秒恢复（如登录跳转回来）
    var key = 'lastResult_' + offerId;
    var cached = sessionStorage.getItem(key);
    if (cached) {
      try {
        var result = JSON.parse(cached);
        render(result);
        // 恢复输入框
        var input = document.getElementById('searchInput');
        if (input) input.value = result.itemUrl || 'https://detail.1688.com/offer/' + offerId + '.html';
        return;
      } catch (e) { /* JSON 损坏，走正常流程 */ }
    }

    // 2. 已登录 → 优先查 DB（历史→inspect 秒出，不扣 Apify 配额）
    var user = (typeof checkAuth === 'function') ? checkAuth() : null;
    if (user) {
      var lang = (typeof I18N !== 'undefined' && I18N.getLocale && I18N.getLocale()) || '';
      API.getReport(offerId, lang)
        .then(function (data) {
          if (data && data.code === 200 && data.data && data.data.status === 'done' && data.data.result) {
            render(data.data.result);
            cacheLastResult(offerId, data.data.result);
            var input = document.getElementById('searchInput');
            if (input) input.value = data.data.result.itemUrl || 'https://detail.1688.com/offer/' + offerId + '.html';
          } else {
            // DB 无记录（可能已被删除）→ 清除保存标记，回退 Apify
            sessionStorage.removeItem('saved_' + offerId);
            _enterSearching(t('search.analyzing', '分析中...'));
            startAnalysis('https://detail.1688.com/offer/' + offerId + '.html');
          }
        })
        .catch(function () {
          // 网络/服务异常 → 清除保存标记，回退 Apify
          sessionStorage.removeItem('saved_' + offerId);
          _enterSearching(t('search.analyzing', '分析中...'));
          startAnalysis('https://detail.1688.com/offer/' + offerId + '.html');
        });
      return;
    }

    // 3. 未登录 → 直接走 Apify
    _enterSearching(t('search.analyzing', '分析中...'));
    startAnalysis('https://detail.1688.com/offer/' + offerId + '.html');
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
    resetSearchBtn();

    // display 缺失时从 mapped verdict 构造最小 display 兜底（旧格式兼容）
    if (!result.display && (result.verdict_product || result.verdict_factory || result.verdict_sample)) {
      console.warn('[inspect] display 缺失，降级到 verdict 兜底');
      result.display = {
        title: result.title || '',
        price: result.price || {},
        productEval: { verdict: result.verdict_product || '', grade: 'none' },
        supplierEval: { verdict: result.verdict_factory || '', grade: 'none' },
        summaryLine: { headline: result.verdict_product || '', reason: '' }
      };
    }

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
    if (!_offerId) return;

    var saveBarCard = document.getElementById('saveBarCard');

    // 已登录 → 走保存流程
    var user = (typeof checkAuth === 'function') ? checkAuth() : null;
    if (user) {
      // 检查 sessionStorage 是否已保存（同会话内秒显）
      var savedKey = 'saved_' + _offerId;
      if (sessionStorage.getItem(savedKey)) {
        showSavedState(saveBar, saveBtn);
        return;
      }

      if (saveBarCard) saveBarCard.style.display = '';
      saveBar.style.display = 'flex';
      saveBar.className = 'save-bar';
      saveBtn.textContent = t('report.saveBtn', '💾 Save');
      saveBtn.disabled = false;
      saveBtn.classList.remove('saved');
      saveBtn.onclick = function () { doSave(saveBtn); };
      return;
    }

    // 未登录 → 引导登录（带 returnPath 回到当前页）
    if (saveBarCard) saveBarCard.style.display = '';
    saveBar.style.display = 'flex';
    saveBar.className = 'save-bar login-hint';
    saveBtn.textContent = t('report.saveBtn', '💾 Save');
    saveBtn.disabled = false;
    saveBtn.classList.remove('saved');
    saveBtn.onclick = function () {
      var returnPath = '/inspect.html?offerId=' + encodeURIComponent(_offerId);
      window.location.href = '/api/auth/google/login?redirect=' + encodeURIComponent(returnPath);
    };
  }

  function showSavedState(saveBar, saveBtn) {
    saveBar.style.display = 'flex';
    saveBar.className = 'save-bar';
    saveBtn.textContent = t('report.savedBtn', '✓ Saved');
    saveBtn.disabled = true;
    saveBtn.classList.add('saved');
    saveBtn.onclick = null;
  }

  function doSave(saveBtn) {
    if (!_offerId) return;
    saveBtn.disabled = true;
    saveBtn.textContent = t('report.savingBtn', 'Saving...');

    API.saveReport(_offerId)
      .then(function (r) {
        if (r && r.code === 200) {
          sessionStorage.setItem('saved_' + _offerId, '1');
          saveBtn.textContent = t('report.savedBtn', '✓ Saved');
          saveBtn.classList.add('saved');
          saveBtn.onclick = null;
          if (typeof Messages !== 'undefined') {
            Messages.success('SAVE_OK', 'Saved!');
          }
        } else if (r && r.code === 409) {
          // 已达 20 条上限
          saveBtn.textContent = t('report.saveBtn', '💾 Save');
          saveBtn.disabled = false;
          if (typeof Messages !== 'undefined') {
            Messages.warning('SAVE_LIMIT_EXCEEDED',
              '已达 20 条保存上限<br><small style="color:var(--ink-3)">请前往历史记录删除旧记录后再保存</small>');
          }
        } else if (r && r.code === 410) {
          // 缓存过期
          saveBtn.textContent = t('report.expiredBtn', '⚠ Expired');
          saveBtn.disabled = true;
        } else if (r && r.code === 401) {
          saveBtn.textContent = t('report.saveBtn', '💾 Save');
          saveBtn.disabled = false;
        } else {
          saveBtn.textContent = t('report.saveBtn', '💾 Save');
          saveBtn.disabled = false;
        }
      })
      .catch(function () {
        saveBtn.textContent = t('report.saveBtn', '💾 Save');
        saveBtn.disabled = false;
      });
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

    // Meta 行：起订 / 月销 / 好评 / 排名 — 只选直接子 span，避开嵌套 i18n
    var metaSpans = document.querySelectorAll('.p01-meta > span');
    if (metaSpans.length >= 2) {
      metaSpans[0].innerHTML = '📦 ' + t('inspect.moq', 'MOQ') + ' <b>' + escHtml(p.moq || '—') + '</b>';
    }
    // 月销来自 product_mapper.sold
    if (metaSpans.length >= 3 && d.sales && d.sales.sold) {
      metaSpans[1].innerHTML = '📊 ' + escHtml(d.sales.sold);
    }
    // 好评率
    if (metaSpans.length >= 4) {
      var rateText = d.badges && d.badges.length ? '' : '—';
      metaSpans[2].innerHTML = rateText || '⭐ <b>—</b>';
      // 尝试从 badges 中找复购率显示
      if (d.badges && d.badges.length > 0) {
        for (var i = 0; i < d.badges.length; i++) {
          if (d.badges[i].text && d.badges[i].text.indexOf('%') !== -1) {
            metaSpans[2].innerHTML = '⭐ <b>' + escHtml(d.badges[i].text) + '</b>';
            break;
          }
        }
      }
      // 好评率优先
      if (d.productEval && d.productEval.dimensions) {
        var peDims = d.productEval.dimensions;
        for (var j = 0; j < peDims.length; j++) {
          if (peDims[j].key === 'd4') {
            metaSpans[2].innerHTML = '⭐ <b>' + escHtml(peDims[j].data || '—') + '</b>';
            break;
          }
        }
      }
    }
    // 排名
    if (metaSpans.length >= 4) {
      var rankText = (d.factory && d.factory.rankText) ? d.factory.rankText : '';
      metaSpans[3].innerHTML = rankText ? escHtml(rankText) : '';
      metaSpans[3].style.display = rankText ? '' : 'none';
    }

    // 阶梯价格
    var tierEl = document.querySelector('.p01-tier');
    if (tierEl) {
      var tiers = d.priceTiers || [];
      if (tiers.length > 0) {
        tierEl.style.display = '';
        var tierHtml = '';
        for (var k = 0; k < Math.min(tiers.length, 3); k++) {
          var t2 = tiers[k];
          var range = t2.qty_min != null ? (escHtml(t2.qty_min) + (t2.qty_max != null ? ('-' + escHtml(t2.qty_max)) : '+')) : '';
          tierHtml += '<span>' + range + '件 <b>¥' + (t2.unit_price != null ? escHtml(Number(t2.unit_price).toFixed(2)) : '—') + '</b></span>';
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
        '<span class="eval-dim-data' + (dim.na ? ' is-na' : '') + '">' + escHtml(dim.data || '') + '</span>' +
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

    // 维度行（3 维度 × 0-3 分 = 9 满分）
    for (var i = 0; i < dims.length; i++) {
      var dim = dims[i];
      var label = (dim.label || dim.icon + ' ' + dim.name || '').trim();
      // D2 认证 — 加 ？帮助按钮
      var helpHtml = (i === 1) ? ' <span class="eval-help" data-action="toggleHelp">？</span>' : '';
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">' + escHtml(label) + helpHtml + '</span>' +
        '<span class="eval-dim-data' + (dim.na ? ' is-na' : '') + '">' + escHtml(dim.data || '') + '</span>' +
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
        '<span class="eval-dim-label">🏢 ' + t('inspect.companyName', '公司名称') + ' <span class="eval-help" data-action="toggleHelp">？</span></span>' +
        '<span class="eval-dim-data">' + escHtml(companyName) + '</span>' +
        '<span class="eval-dim-ref"></span>' +
        '</div>';
      html += '<div class="eval-help-text">' + escHtml((d.factory && d.factory.companyNameExplain) || '') + '</div>';
    }

    // 附加信息：产业带
    var cluster = se.industryCluster || '';
    if (cluster) {
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">📍 ' + t('inspect.industryCluster', '产业带') + ' <span class="eval-help" data-action="toggleHelp">？</span></span>' +
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

    // 国际运费：根据页面语言匹配国家
    var loc = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() : 'en';
    var dest = DEST_MAP[loc] || 'VN';
    var ship = shipRates[dest];
    var shipLow = ship.eco[0], shipHigh = ship.eco[1];

    // 合计（定金 USD + 运费 USD + 服务费 USD）
    var depositUsd = depositCny / USD_RATE;
    var totalLow = depositUsd + shipLow + SERVICE_FEE;
    var totalHigh = depositUsd + shipHigh + SERVICE_FEE;
    var totalEl = document.getElementById('totalFee');
    if (totalEl) {
      totalEl.textContent = I18N && I18N.formatPriceRange
        ? I18N.formatPriceRange(totalLow, totalHigh)
        : ('$' + Math.round(totalLow) + ' – $' + Math.round(totalHigh));
    }

    // 尾款合计（运费 + 服务费）
    var balanceEl = document.getElementById('balanceTotal');
    if (balanceEl) {
      var balLow = shipLow + SERVICE_FEE;
      var balHigh = shipHigh + SERVICE_FEE;
      balanceEl.textContent = I18N && I18N.formatPriceRange
        ? I18N.formatPriceRange(balLow, balHigh)
        : ('$' + Math.round(balLow) + ' – $' + Math.round(balHigh));
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
  // 骨架屏
  // ====================================================================

  function hideSkeleton() {
    var skel = document.getElementById('skeleton');
    if (skel) skel.style.display = 'none';
  }

  function showInspectError(titleKey, titleFallback) {
    hideSkeleton();
    resetSearchBtn();
    var err = document.getElementById('inspectError');
    if (!err) return;
    err.style.display = '';
    if (titleKey) {
      var titleEl = document.getElementById('errorTitle');
      if (titleEl) titleEl.textContent = titleFallback || t(titleKey, titleFallback || '');
      var msgEl = document.getElementById('errorMsg');
      if (msgEl) msgEl.textContent = '';
    }
  }

  function resetSearchBtn() {
    _searching = false;
    var btn = document.getElementById('searchBtn');
    if (btn) {
      var input = document.getElementById('searchInput');
      btn.disabled = !(input && input.value.trim());
      btn.textContent = t('search.button', '分析');
    }
    var hint = document.querySelector('.search-hint');
    if (hint) hint.textContent = t('search.hint', '每日免费 3 次 · 登陆后10次/日');
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
    _debug: function () {
      return {
        _searching: _searching,
        _offerId: _offerId,
        USD_RATE: USD_RATE,
        _samplePrice: _samplePrice,
        _sampleMoq: _sampleMoq,
        _sampleQty: _sampleQty,
        _pollTimer: !!_pollTimer
      };
    }
  };

  // ====================================================================
  // 顶部搜索栏
  // ====================================================================

  function setupSearch() {
    var input = document.getElementById('searchInput');
    var btn = document.getElementById('searchBtn');
    var hint = document.querySelector('.search-hint');
    if (!input || !btn) return;

    btn.disabled = true;

    function doSearch(val) {
      if (!val || _searching) return;
      var url;
      if (val.indexOf('detail.1688.com') !== -1) {
        url = val;
      } else {
        var m = val.match(/offer(?:Id)?[=/](\d+)/i);
        if (m) {
          url = 'https://detail.1688.com/offer/' + m[1] + '.html';
        }
      }
      if (!url) {
        if (typeof Messages !== 'undefined') {
          Messages.warning('INVALID_URL', '请粘贴有效的 1688 商品链接');
        }
        return;
      }

      _enterSearching(t('search.analyzing', '分析中...'));
      startAnalysis(url);
    }

    input.addEventListener('input', function () {
      btn.disabled = !input.value.trim() || _searching;
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        if (_searching) return;
        doSearch(input.value.trim());
      }
    });

    btn.addEventListener('click', function () {
      if (_searching) return;
      doSearch(input.value.trim());
    });

    // 委托点击事件（替代 HTML 内联 onclick）
    document.addEventListener('click', function (e) {
      var helpEl = e.target.closest('.eval-help');
      if (helpEl && helpEl.dataset.action === 'toggleHelp') toggleHelp(helpEl);
      var groupEl = e.target.closest('[data-action="toggleGroup"]');
      if (groupEl) toggleGroup(groupEl);
      var inspectEl = e.target.closest('[data-action="toggleInspect"]');
      if (inspectEl) toggleInspect();
    });
  }

  // ====================================================================
  // 页面启动
  // ====================================================================

  // beforeunload：清理轮询定时器（铁律五：异步竞态防御）
  window.addEventListener('beforeunload', function () {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

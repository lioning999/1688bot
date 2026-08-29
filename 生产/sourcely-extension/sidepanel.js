// ===== Sourcely Side Panel — 分析报告页 =====
// MV3 标准：纯 UI，零 fetch。所有网络请求通过 API (lib/api.js) 委托给 service-worker.js。

(function () {
  'use strict';

  // ---- DOM 缓存 ----
  var EL = {};
  function cacheDom() {
    EL.tabBtns = document.querySelectorAll('.tab-btn');
    EL.reportTab = document.getElementById('tab-report');
    EL.historyTab = document.getElementById('tab-history');
    // 空态
    EL.emptyNot1688 = document.getElementById('emptyNot1688');
    EL.emptyNotLoggedIn = document.getElementById('emptyNotLoggedIn');
    EL.emptyLoading = document.getElementById('emptyLoading');
    EL.emptyError = document.getElementById('emptyError');
    EL.emptyIdle = document.getElementById('emptyIdle');
    EL.errorMessage = document.getElementById('errorMessage');
    EL.btnRetry = document.getElementById('btnRetry');
    EL.btnLogin = document.getElementById('btnLogin');
    EL.btnLogout = document.getElementById('btnLogout');
    EL.btnAnalyze = document.getElementById('btnAnalyze');
    EL.quotaRemaining = document.getElementById('quotaRemaining');
    // 内容区
    EL.inspectContent = document.getElementById('inspectContent');

    // p01
    EL.p01Img = document.getElementById('p01Img');
    EL.p01Title = document.getElementById('p01Title');
    EL.p01Price = document.getElementById('p01Price');
    EL.p01Unit = document.getElementById('p01Unit');
    EL.p01Moq = document.getElementById('p01Moq');
    EL.p01Sales = document.getElementById('p01Sales');
    EL.p01Tier = document.getElementById('p01Tier');
    EL.p01TierText = document.getElementById('p01TierText');
    // s2
    EL.s2Headline = document.getElementById('s2Headline');
    EL.s2Reason = document.getElementById('s2Reason');
    // eval
    EL.productEvalScore = document.getElementById('productEvalScore');
    EL.productEvalDesc = document.getElementById('productEvalDesc');
    EL.productEvalBody = document.getElementById('productEvalBody');
    EL.supplierEvalScore = document.getElementById('supplierEvalScore');
    EL.supplierEvalDesc = document.getElementById('supplierEvalDesc');
    EL.supplierEvalBody = document.getElementById('supplierEvalBody');
    // sample
    EL.samplePaid = document.getElementById('samplePaid');
    EL.sampleLocked = document.getElementById('sampleLocked');
    EL.depositTotal = document.getElementById('depositTotal');
    EL.feeUnitPrice = document.getElementById('feeUnitPrice');
    EL.feeQty = document.getElementById('feeQty');
    EL.feeDomestic = document.getElementById('feeDomestic');
    EL.balanceTotal = document.getElementById('balanceTotal');
    // member modal
    EL.btnUpgrade = document.getElementById('btnUpgrade');
    EL.memberModal = document.getElementById('memberModal');
    EL.memberClose = document.getElementById('memberClose');
    // lang
    EL.langBtns = document.querySelectorAll('.lang-btn');
    // save — 已移除，分析自动落库
    // share
    // detect bar
    EL.detectBar = document.getElementById('detectBar');
    EL.detectBarBtn = document.getElementById('detectBarBtn');
  }

  // ---- 工具 ----
  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function showCard(el, show) { if (el) el.style.display = show ? '' : 'none'; }

  function showEmpty(state) {
    showCard(EL.emptyNot1688, state === 'not1688');
    showCard(EL.emptyNotLoggedIn, state === 'notLoggedIn');
    showCard(EL.emptyLoading, state === 'loading');
    showCard(EL.emptyError, state === 'error');
    showCard(EL.emptyIdle, state === 'idle');
    showCard(EL.btnAnalyze, state === 'idle');
    showCard(EL.inspectContent, state === 'ready');
    // 退出按钮：已登录时显示
    var loggedIn = checkLoginState();
    showCard(EL.btnLogout, loggedIn);
  }

  // ---- 状态 ----
  var _pollTimer = null;
  var _activeTaskId = null;
  var _searching = false;
  var _currentOfferId = null;
  var _currentPriceLow = 0;   // 主价格 low（已换算目标货币）
  var _currentPriceHigh = null; // 主价格 high（null = 无区间）
  var _currentMoq = 1;
  var _tier = 'free';  // 会员档位：free/paid（fetchQuota 时更新）

  function stopPolling() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }
  }

  // ---- 语言 ----
  function highlightLang(lang) {
    EL.langBtns.forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-lang') === lang);
    });
  }

  // ---- 登录 ----
  function checkLoginState() { return !!API.getToken(); }

  // ---- Tab 切换 ----
  function switchTab(tab) {
    // 未登录 → 不允许切到历史记录，直接回报告页显示登录态
    if (tab === 'history' && !checkLoginState()) {
      tab = 'report';
      showEmpty('notLoggedIn');
    }
    EL.tabBtns.forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tab);
    });
    EL.reportTab.classList.toggle('active', tab === 'report');
    EL.historyTab.classList.toggle('active', tab === 'history');
    if (tab === 'history' && typeof HistoryPage !== 'undefined') HistoryPage.load();
  }

  // ---- 1688 URL 处理 ----
  function extractOfferId(url) {
    if (!url) return null;
    var m = url.match(/offer(?:[Ii][Dd])?[=#/](\d+)/);
    if (m) return m[1];
    m = url.match(/detail\/(\d+)\.html/);
    return m ? m[1] : null;
  }

  // ---- 分析流程 ----
  function startAnalysis(url) {
    if (_searching) return;
    _searching = true;
    showEmpty('loading');
    stopPolling();

    var offerId = extractOfferId(url);
    _currentOfferId = offerId;
    var lang = I18N.getLang();

    API.analyze(url, lang).then(function (res) {
      if (!res || res.code !== 200) {
        _searching = false;
        EL.errorMessage.textContent = I18N.msg(res && res.msg_code, res && res.message) || I18N.t('report.analyzeFailed');
        showEmpty('error');
        return;
      }
      var taskId = res.data && res.data.task_id;
      if (taskId) {
        pollTask(taskId);
      } else {
        _searching = false;
        stopPolling();
        showEmpty('ready');
        render(res.data);
      }
    }).catch(function () {
      _searching = false;
      showEmpty('error');
    });
  }

  function pollTask(taskId, count) {
    count = count || 0;
    _activeTaskId = taskId;
    if (count > 60) {
      _searching = false; stopPolling(); _activeTaskId = null;
      EL.errorMessage.textContent = I18N.t('report.analyzeFailed');
      showEmpty('error'); return;
    }
    _pollTimer = setTimeout(function () {
      API.getTask(taskId).then(function (res) {
        if (taskId !== _activeTaskId) return;
        if (!res || res.code !== 200) {
          _searching = false; stopPolling();
          EL.errorMessage.textContent = I18N.msg(res && res.msg_code, res && res.message) || I18N.t('report.analyzeFailed');
          showEmpty('error'); return;
        }
        if (res.data.status === 'done') {
          _searching = false; stopPolling();
          showEmpty('ready');
          render(res.data.result || res.data);
        } else if (res.data.status === 'failed') {
          _searching = false; stopPolling();
          EL.errorMessage.textContent = I18N.msg(res.msg_code, res.data.error || res.message) || I18N.t('report.analyzeFailed');
          showEmpty('error');
        } else { pollTask(taskId, count + 1); }
      }).catch(function () { _searching = false; stopPolling(); showEmpty('error'); });
    }, 2000);
  }

  // ---- 渲染入口 ----
  function render(data) {
    if (!data) return;
    var display = data.display;
    // ===== TRACE: 打印后端返回的原始 display JSON 字段名 =====
    console.log('[TRACE] display keys:', Object.keys(display || {}));
    if (display && display.productEval) {
      console.log('[TRACE] productEval keys:', Object.keys(display.productEval));
      console.log('[TRACE] productEval.score:', display.productEval.score);
      console.log('[TRACE] productEval.grade:', display.productEval.grade);
      console.log('[TRACE] productEval.verdict:', display.productEval.verdict);
      if (display.productEval.dimensions && display.productEval.dimensions[0]) {
        console.log('[TRACE] productEval.dim[0] KEYS:', Object.keys(display.productEval.dimensions[0]));
        console.log('[TRACE] productEval.dim[0] RAW:', JSON.stringify(display.productEval.dimensions[0]));
      }
      console.log('[TRACE] productEval.stockLevel:', display.productEval.stockLevel);
    }
    if (display && display.supplierEval) {
      console.log('[TRACE] supplierEval keys:', Object.keys(display.supplierEval));
      console.log('[TRACE] supplierEval.score:', display.supplierEval.score);
      console.log('[TRACE] supplierEval.grade:', display.supplierEval.grade);
      console.log('[TRACE] supplierEval.verdict:', display.supplierEval.verdict);
      if (display.supplierEval.dimensions && display.supplierEval.dimensions[0]) {
        console.log('[TRACE] supplierEval.dim[0] KEYS:', Object.keys(display.supplierEval.dimensions[0]));
        console.log('[TRACE] supplierEval.dim[0] RAW:', JSON.stringify(display.supplierEval.dimensions[0]));
      }
      console.log('[TRACE] supplierEval.companyName:', display.supplierEval.companyName);
      console.log('[TRACE] supplierEval.industryCluster:', display.supplierEval.industryCluster);
    }
    if (display && display.summaryLine) {
      console.log('[TRACE] summaryLine keys:', Object.keys(display.summaryLine));
      console.log('[TRACE] summaryLine.headline:', display.summaryLine.headline);
      console.log('[TRACE] summaryLine.reason:', display.summaryLine.reason);
    }
    if (display && display.factory) {
      console.log('[TRACE] factory.rankText:', display.factory.rankText);
    }
    // ===== TRACE END =====
    if (!display) {
      // 兜底：用顶层字段拼最小 display
      display = {
        title: data.title || '',
        price: { low: data.priceCNY ? data.priceCNY.low : 0, high: data.priceCNY ? data.priceCNY.high : 0, unit: '', moq: 0 },
        sales: data.sales || {},
        productEval: { verdict: '', score: 0, max_score: 18, grade: 'none', dimensions: [] },
        supplierEval: { verdict: '', score: 0, max_score: 9, grade: 'none', dimensions: [] },
        summaryLine: {}
      };
    }

    // 分析时间
    var analyzedAt = data.analyzed_at;
    if (analyzedAt) {
      var daysAgo = Math.max(0, Math.floor((Date.now() / 1000 - analyzedAt) / 86400));
      var metaEl = document.getElementById('reportMeta');
      if (metaEl) {
        metaEl.textContent = I18N.t('report.analyzedAt').replace('{n}', daysAgo);
        metaEl.style.display = '';
      }
    }

    renderP01(display);
    renderSummary(display);
    renderProductEval(display.productEval, display);
    renderSupplierEval(display.supplierEval, display);
    renderSample(display.price || {});

    hideDetectBar();  // 新报告覆盖，清除检测条
  }

  // ① 产品确认
  function renderP01(display) {
    var p = display.price || {};
    var imgUrl = (display.images && display.images[0]) ? display.images[0] : '';
    if (imgUrl) {
      EL.p01Img.src = imgUrl;
      EL.p01Img.style.display = '';
    } else {
      EL.p01Img.style.display = 'none';
    }

    EL.p01Title.textContent = display.title || '—';

    if (p.low != null) {
      EL.p01Price.textContent = fmtMoney(p.low);
      if (p.high != null && p.high !== p.low) EL.p01Price.textContent += ' – ' + fmtMoney(p.high);
      _currentPriceLow = Number(p.low);
      _currentPriceHigh = (p.high != null && p.high !== p.low) ? Number(p.high) : null;
    } else {
      EL.p01Price.textContent = '—';
      _currentPriceLow = 0;
      _currentPriceHigh = null;
    }
    EL.p01Unit.textContent = '/' + (p.unit ? escHtml(p.unit) : (I18N.t('inspect.piecesUnit') || '件'));

    EL.p01Moq.textContent = p.moq != null ? String(p.moq) : '—';
    _currentMoq = p.moq || 1;

    if (display.sales && display.sales.sold) {
      EL.p01Sales.textContent = display.sales.sold;
    } else {
      EL.p01Sales.textContent = '—';
    }

    // 阶梯价格（无数据不显示）
    var tiers = display.priceTiers || [];
    if (tiers.length > 0) {
      var parts = [];
      for (var i = 0; i < Math.min(tiers.length, 3); i++) {
        var t = tiers[i];
        var range = t.qty_min != null ? (escHtml(t.qty_min) + (t.qty_max != null ? ('-' + escHtml(t.qty_max)) : '+')) : '';
        parts.push(range + (I18N.t('inspect.piecesUnit') || '件') + ' ' + (t.unit_price != null ? fmtMoney(t.unit_price) : '—'));
      }
      EL.p01Tier.style.display = '';
      EL.p01TierText.innerHTML = parts.join(' │ ');
    } else {
      EL.p01Tier.style.display = 'none';
    }
  }

  // ② 综合结论
  function renderSummary(display) {
    var summary = display.summaryLine || {};
    var grade = summary.grade || 'none';

    var headline = typeof summary.headline === 'object' ? (summary.headline.key || '') : (summary.headline || '');
    // "TODO" 或空 → 用 grade 生成兜底标题
    if (!headline || headline === 'TODO') {
      var gradeLabels = { go: I18N.t('report.grade.go'), ok: I18N.t('report.grade.ok'), bad: I18N.t('report.grade.bad'), none: I18N.t('report.grade.none') };
      headline = gradeLabels[grade] || '';
    }
    EL.s2Headline.textContent = headline || '—';
    EL.s2Headline.className = 's2-headline ' + grade;

    var reason = typeof summary.reason === 'object' ? (summary.reason.key || '') : (summary.reason || '');
    if (reason === 'TODO') reason = '';
    EL.s2Reason.textContent = reason;
  }

  // ③④ 评测组 — 维度行共享 helper
  function _renderDimRows(dims) {
    var html = '';
    (dims || []).forEach(function (d) {
      if (typeof d !== 'object' || !d) return;
      // 维度标记：score>=2 → ✔, score==1 → ✕, score==0 或 na → —
      var mark = '';
      var markClass = '';
      if (d.na || d.score === 0) {
        mark = '—'; markClass = 'none';
      } else if (d.score >= 2) {
        mark = '✔'; markClass = 'good';  // ✔
      } else {
        mark = '✘'; markClass = 'bad';   // ✕
      }
      var icon = d.icon || '';
      var name = (d.label && d.label !== d.name) ? d.label : (d.name || '');
      if (!name) name = d.icon + ' ' + (d.name || '');
      else if (icon && name.indexOf(icon) === -1) name = icon + ' ' + name;
      // 数据列：后端字段是 data，不是 data_text
      var value = d.data || '';
      // 标杆列：后端字段是 ref，不是 benchmark_text
      var bench = d.ref || '';
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-mark ' + markClass + '">' + mark + '</span>' +
        '<span class="eval-dim-label">' + escHtml(name) + '</span>' +
        '<span class="eval-dim-data' + (d.na ? ' is-na' : '') + '">' + escHtml(value) + '</span>' +
        (bench ? '<span class="eval-dim-bench">' + escHtml(bench) + '</span>' : '') +
        '</div>';
    });
    return html;
  }

  function _renderEvalHeader(evalData, scoreEl, descEl, maxScore) {
    if (!evalData) {
      scoreEl.textContent = '—/' + maxScore + ' ' + I18N.t('report.scoreUnit');
      scoreEl.className = 'eval-group-score none';
      descEl.textContent = '';
      return 'none';
    }
    var score = evalData.score != null ? evalData.score : '—';
    var grade = evalData.grade || 'none';
    scoreEl.textContent = score + '/' + maxScore + ' ' + I18N.t('report.scoreUnit');
    scoreEl.className = 'eval-group-score ' + grade;
    // desc 用 summary（短描述），不用 verdict（长判词）
    var desc = evalData.summary || evalData.verdict || '';
    if (typeof desc === 'object') desc = desc.key || '';
    descEl.textContent = String(desc);
    return grade;
  }

  // ③ 产品验证
  function renderProductEval(evalData, display) {
    var grade = _renderEvalHeader(evalData, EL.productEvalScore, EL.productEvalDesc, 18);

    if (!evalData) {
      EL.productEvalBody.innerHTML = '<div class="eval-dim"><span class="eval-dim-data" style="color:var(--ink-3)">—</span></div>';
      return;
    }

    var html = _renderDimRows(evalData.dimensions);

    // 补充：库存状态
    var stock = evalData.stockLevel;
    if (stock) {
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">📦 ' + (I18N.t('inspect.stock') || '库存') + '</span>' +
        '<span class="eval-dim-data">' + escHtml(stock.text) + '</span>' +
        '</div>';
    }

    // 补充：排名（来自 factory.rankText）
    var rankText = (display.factory && display.factory.rankText) ? display.factory.rankText : '';
    if (rankText) {
      var rankData = String(rankText).replace(/^🏆\s*/, '');
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">🏆 ' + (I18N.t('inspect.rank') || '排名') + '</span>' +
        '<span class="eval-dim-data">' + escHtml(rankData) + '</span>' +
        '</div>';
    }

    // 判词
    if (evalData.verdict) {
      var v = typeof evalData.verdict === 'object' ? (evalData.verdict.key || String(evalData.verdict)) : String(evalData.verdict);
      html += '<div class="eval-human ' + grade + '">💬 ' + escHtml(v) + '</div>';
    }

    EL.productEvalBody.innerHTML = html || '<div class="eval-dim"><span class="eval-dim-data" style="color:var(--ink-3)">—</span></div>';
  }

  // ④ 供应商验证
  function renderSupplierEval(evalData, display) {
    var grade = _renderEvalHeader(evalData, EL.supplierEvalScore, EL.supplierEvalDesc, 9);

    if (!evalData) {
      EL.supplierEvalBody.innerHTML = '<div class="eval-dim"><span class="eval-dim-data" style="color:var(--ink-3)">—</span></div>';
      return;
    }

    var html = _renderDimRows(evalData.dimensions);

    // 补充：公司名称
    var companyName = evalData.companyName || (display.factory && display.factory.supplierName) || '';
    if (companyName) {
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">🏢 ' + (I18N.t('inspect.companyName') || '公司名称') + '</span>' +
        '<span class="eval-dim-data">' + escHtml(companyName) + '</span>' +
        '</div>';
    }

    // 补充：产业带
    var cluster = evalData.industryCluster || '';
    if (cluster) {
      html += '<div class="eval-dim">' +
        '<span class="eval-dim-label">📍 ' + (I18N.t('inspect.industryCluster') || '产业带') + '</span>' +
        '<span class="eval-dim-data">' + escHtml(cluster) + '</span>' +
        '</div>';
    }

    // 判词
    if (evalData.verdict) {
      var v = typeof evalData.verdict === 'object' ? (evalData.verdict.key || String(evalData.verdict)) : String(evalData.verdict);
      html += '<div class="eval-human ' + grade + '">💬 ' + escHtml(v) + '</div>';
    }

    EL.supplierEvalBody.innerHTML = html || '<div class="eval-dim"><span class="eval-dim-data" style="color:var(--ink-3)">—</span></div>';
  }

  // ⑤ 拿样验货（付费显示拿样卡，免费显示锁态卡）
  function renderSample(price) {
    _currentMoq = price.moq || 1;
    updateFee();
    updateSampleTier();
  }

  // 按会员档位切换拿样区两态
  function updateSampleTier() {
    var isPaid = _tier === 'paid';
    showCard(EL.samplePaid, isPaid);
    showCard(EL.sampleLocked, !isPaid);
  }

  // 货币格式化：符号来自 i18n（zh 默认 ¥），小数位按语言（VND/THB 0 位，USD/CNY 2 位）
  function fmtMoney(n) {
    var lang = I18N.getLang();
    var sym = I18N.t('currency.symbol') || '¥';
    var dec = { en: 2, vi: 0, th: 0, zh: 2 }[lang];
    if (dec == null) dec = 2;
    return sym + Number(n).toLocaleString(lang, { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }

  // 拿样费用常量：国内邮 ¥10 / 服务费 $10 / 国际运费 $3-6（实际结算币种，不随语言切换）
  var SAMPLE_FEE = { domesticFreight: 10, serviceFee: 10, intlFreightLow: 3, intlFreightHigh: 6 };

  // 费用计算（定金=商品×MOQ+国内邮¥10；尾款=服务费$10+国际$3-6，固定区间）
  function updateFee() {
    var unitPrice = _currentPriceLow || 0;
    var qty = _currentMoq || 1;
    var depositTotal = unitPrice * qty + SAMPLE_FEE.domesticFreight;

    EL.feeUnitPrice.textContent = fmtMoney(unitPrice);
    EL.feeQty.textContent = String(qty);
    EL.feeDomestic.textContent = '¥' + SAMPLE_FEE.domesticFreight.toFixed(2);
    EL.depositTotal.textContent = fmtMoney(depositTotal);

    var balLow = SAMPLE_FEE.serviceFee + SAMPLE_FEE.intlFreightLow;
    var balHigh = SAMPLE_FEE.serviceFee + SAMPLE_FEE.intlFreightHigh;
    EL.balanceTotal.textContent = '$' + balLow + '–$' + balHigh;
  }

  // 切换语言时重渲染价格（主价格 + 拿样区），符号/小数位跟着语言变
  function refreshPrices() {
    if (_currentPriceLow > 0) {
      EL.p01Price.textContent = fmtMoney(_currentPriceLow);
      if (_currentPriceHigh != null) EL.p01Price.textContent += ' – ' + fmtMoney(_currentPriceHigh);
    } else {
      EL.p01Price.textContent = '—';
    }
    updateFee();
  }

  // ---- 事件 ----
  function bindEvents() {
    EL.tabBtns.forEach(function (btn) {
      btn.addEventListener('click', function () { switchTab(btn.getAttribute('data-tab')); });
    });

    EL.btnRetry.addEventListener('click', function () {
      API.getCurrentTabUrl().then(function (res) {
        if (res && res.url) startAnalysis(res.url);
        else showEmpty('not1688');
      });
    });

    EL.btnLogin.addEventListener('click', function () {
      console.log('[SidePanel] LOGIN button clicked');
      // MV3 标准：登录委托给 service worker 的 launchWebAuthFlow；lang 随消息传入，SW 同步读避免异步丢手势
      chrome.runtime.sendMessage({ type: 'LOGIN', payload: { lang: I18N.getLang() } }, function (res) {
        console.log('[SidePanel] LOGIN response received, code=' + (res && res.code));
        if (res && res.code === 200 && res.data && res.data.token) {
          console.log('[SidePanel] LOGIN success, token saved');
          API.setToken(res.data.token);
          Toast.show(I18N.t('plugin.loginSuccess') || '登录成功', 'success');
          showCard(EL.btnLogout, true);
          handleTabChange(null);
        } else {
          var msg = I18N.msg(res && res.msg_code, res && res.message) || I18N.t('plugin.loginFailed') || 'Login failed';
          console.error('[SidePanel] LOGIN failed:', msg);
          Toast.show(msg, 'error');
        }
      });
    });

    // 退出登录
    EL.btnLogout.addEventListener('click', function () {
      API.clearToken();
      stopPolling(); _activeTaskId = null; _searching = false;  // 停掉进行中的分析轮询，否则会 401 回来覆盖界面
      _currentOfferId = null;  // 清除报告状态，允许 tab 切换重新检测
      hideDetectBar();
      showCard(EL.btnLogout, false);
      showEmpty('notLoggedIn');
      if (typeof HistoryPage !== 'undefined') HistoryPage.reset();  // 历史页也回到未登录态
      Toast.show(I18N.t('plugin.logoutSuccess') || '已退出登录', 'info');
    });

    EL.btnAnalyze.addEventListener('click', function () {
      API.getCurrentTabUrl().then(function (res) {
        if (!res || !res.url) { showEmpty('not1688'); return; }
        startAnalysis(res.url);
      });
    });

    // 折叠
    document.querySelectorAll('.eval-group-header').forEach(function (hdr) {
      hdr.addEventListener('click', function () {
        hdr.closest('.eval-group').classList.toggle('open');
      });
    });

    // 会员弹层
    EL.btnUpgrade.addEventListener('click', function () { EL.memberModal.style.display = 'flex'; });
    EL.memberClose.addEventListener('click', function () { EL.memberModal.style.display = 'none'; });
    document.querySelectorAll('[data-action="closeMember"]').forEach(function (el) {
      el.addEventListener('click', function () { EL.memberModal.style.display = 'none'; });
    });

    // 语言切换
    EL.langBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var lang = btn.getAttribute('data-lang');
        I18N.switchTo(lang, refreshPrices);
        highlightLang(lang);
      });
    });

    // 检测条：分析当前标签页商品
    if (EL.detectBarBtn) {
      EL.detectBarBtn.addEventListener('click', function () {
        hideDetectBar();
        API.getCurrentTabUrl().then(function (res) {
          if (res && res.url) startAnalysis(res.url);
        });
      });
    }
  }

  // ---- 入口 ----
  function handleTabChange(urlFromMsg) {
    if (urlFromMsg) {
      // 从消息回调中直接处理
      processUrl(urlFromMsg);
      return;
    }
    // 主动获取
    API.getCurrentTabUrl().then(function (res) { processUrl(res && res.url); });
  }

  function processUrl(url) {
    // 已有报告渲染 → 检测是否切到不同1688商品，显示检测条
    if (_currentOfferId) {
      var newOfferId = extractOfferId(url || '');
      if (newOfferId && newOfferId !== _currentOfferId) {
        showDetectBar(newOfferId);
      } else if (newOfferId === _currentOfferId) {
        hideDetectBar();
      }
      // 不重置报告
      return;
    }
    if (!url) { showEmpty('not1688'); return; }
    var offerId = extractOfferId(url);
    if (!offerId) {
      showEmpty('not1688');
      stopPolling(); _activeTaskId = null; _searching = false; _currentOfferId = null;
      return;
    }
    if (offerId === _currentOfferId && _currentOfferId) return;

    stopPolling(); _activeTaskId = null; _searching = false; _currentOfferId = null;

    if (!checkLoginState()) {
      showEmpty('notLoggedIn');
      return;
    }
    showEmpty('idle');
    fetchQuota();
  }

  var _detectedOfferId = null;
  function showDetectBar(offerId) {
    _detectedOfferId = offerId;
    if (EL.detectBar) EL.detectBar.style.display = 'flex';
  }
  function hideDetectBar() {
    _detectedOfferId = null;
    if (EL.detectBar) EL.detectBar.style.display = 'none';
  }

  function fetchQuota() {
    console.log('[SidePanel] fetchQuota called, token=' + (API.getToken() ? 'YES' : 'NO'));
    API.getQuota().then(function (res) {
      console.log('[SidePanel] fetchQuota response:', res);
      if (res && res.code === 200 && res.data && res.data.remaining != null) {
        EL.quotaRemaining.textContent = res.data.remaining;
        _tier = res.data.tier === 'paid' ? 'paid' : 'free';
        updateSampleTier();
        console.log('[SidePanel] quota updated:', res.data.remaining, 'tier=', _tier);
      } else {
        EL.quotaRemaining.textContent = '—';
        console.warn('[SidePanel] quota fetch unexpected response:', res);
      }
    }).catch(function (e) {
      EL.quotaRemaining.textContent = '—';
      console.error('[SidePanel] quota fetch error:', e);
    });
  }

  // ---- 初始化 ----
  function init() {
    cacheDom();
    bindEvents();
    var ready = 0;
    function onReady() {
      if (++ready === 2) {
        highlightLang(I18N.getLang());
        handleTabChange(null);
      }
    }
    API.loadTokenFromStorage(onReady);
    I18N.detect(onReady);

    // 监听 tab URL 变化
    if (chrome && chrome.tabs) {
      chrome.tabs.onActivated.addListener(function (activeInfo) {
        chrome.tabs.get(activeInfo.tabId, function (tab) { processUrl(tab && tab.url); });
      });
      chrome.tabs.onUpdated.addListener(function (tabId, changeInfo, tab) {
        if (changeInfo.url) processUrl(changeInfo.url);
      });
    }
  }

  window.addEventListener('pagehide', function () { stopPolling(); });

  // 桥接给 history.js：点历史时先清空旧内容显示加载，避免切换语言后旧语言报告残留
  window._showReportLoading = function () {
    showEmpty('loading');
  };

  // 桥接给 history.js
  window._renderReport = function (displayData) {
    var display = displayData.display || displayData;
    if (!display) return;
    stopPolling(); _activeTaskId = null; _searching = false;  // 停掉进行中的轮询，避免历史报告被分析结果顶掉
    showEmpty('ready');
    render({ display: display });
    fetchQuota();  // 历史报告路径不走 processUrl，补一次刷新 tier + 配额
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

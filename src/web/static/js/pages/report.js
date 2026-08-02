// ===== report.js — 1688 商品分析报告页 =====
// 依赖：api/core.js, utils/share.js, utils/i18n.js, utils/components.js
(function () {
  'use strict';

  // i18n helper — returns translation or fallback
  function t(key, fallback) {
    return (typeof I18N !== 'undefined' && I18N.t) ? (I18N.t(key) || fallback) : fallback;
  }

  // ===== DOM 引用 =====
  var searchBtn = document.getElementById('searchBtn');
  var searchInput = document.getElementById('searchInput');
  var searchHint = document.querySelector('.search-hint');
  var isSearching = false;
  var _pollTimer = null;  // Bug #14：定时器引用，beforeunload 时清理

  // 初始状态：空输入时按钮禁用
  searchBtn.disabled = true;
  searchInput.addEventListener('input', function () {
    searchBtn.disabled = !searchInput.value.trim() || isSearching;
  });

  // ===== 搜索按钮 =====
  searchBtn.addEventListener('click', function () {
    if (isSearching) return;
    var url = searchInput.value.trim();
    if (!url) return;

    isSearching = true;
    showProgress();
    searchBtn.disabled = true;
    searchBtn.textContent = t('search.analyzing', '分析中...');
    searchHint.textContent = t('report.analyzing', '分析中...');

    startAnalysis(url);
  });

  // ===== API 调用（委托给 api/core.js） =====

  function startAnalysis(url) {
    var lang = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() : '';
    API.analyze(url, lang)
      .then(function (data) {
        if (data.code !== 200) {
          // _handleCommonErrors 已统一弹 Toast（403配额/401未登录/5xx）
          // 这里只更新页面状态，不重复弹 Toast
          hideProgress();
          resetSearchButton();
          searchHint.textContent = data.message || t('report.startFailed', '分析启动失败');
          searchHint.style.color = 'var(--seal)';
          setTimeout(function () {
            searchHint.textContent = t('search.hint', '每日免费 3 次 · WhatsApp 登记后不限次数');
            searchHint.style.color = '';
          }, 5000);
          return;
        }
        var taskId = data.data && data.data.task_id;
        if (!taskId || typeof taskId !== 'string') {
          hideProgress();
          resetSearchButton();
          Messages.error('ANALYSIS_FAILED', '分析启动失败，请稍后重试');
          return;
        }
        sessionStorage.setItem('lastTaskId', taskId);
        pollTask(taskId, 0);
      })
      .catch(function (err) {
        hideProgress();
        resetSearchButton();
        Messages.error('NETWORK_ERROR', '网络错误，请检查网络后重试');
        console.warn('Analyze start failed:', err);
      });
  }

  function pollTask(taskId, attempt) {
    if (attempt > 60) {
      hideProgress();
      resetSearchButton();
      sessionStorage.removeItem('lastTaskId');
      Messages.error('ANALYSIS_TIMEOUT', '分析超时，请稍后重试');
      return;
    }

    API.getTask(taskId)
      .then(function (data) {
        var task = data.data;
        if (!task) {
          hideProgress();
          resetSearchButton();
          sessionStorage.removeItem('lastTaskId');
          Messages.error('TASK_EXPIRED', '任务不存在或已过期');
          return;
        }

        if (task.status === 'done') {
          resetSearchButton();
          searchHint.textContent = t('search.hint', '每日免费 3 次 · WhatsApp 登记后不限次数');
          sessionStorage.removeItem('lastTaskId');
          renderResult(task.result);
          if (task.result && task.result.offerId) {
            sessionStorage.setItem('lastResult_' + task.result.offerId, JSON.stringify(task.result));
          }
          if (task.warning) Messages.warning(task.warning_msg_code || 'STALE_DATA', task.warning);
        } else if (task.status === 'failed') {
          hideProgress();
          resetSearchButton();
          sessionStorage.removeItem('lastTaskId');
          Messages.error(task.error_msg_code || 'ANALYSIS_FAILED', task.error || '分析失败，请稍后重试');
        } else {
          // 进度由 progress-card 组件展示，这里保持简洁
          _pollTimer = setTimeout(function () { pollTask(taskId, attempt + 1); }, 2000);
        }
      })
      .catch(function (err) {
        hideProgress();
        resetSearchButton();
        Messages.error('NETWORK_ERROR', '网络错误，请检查网络后重试');
        console.warn('Poll failed:', err);
        sessionStorage.removeItem('lastTaskId');
      });
  }

  function resetSearchButton() {
    isSearching = false;
    searchBtn.disabled = !searchInput.value.trim();
    searchBtn.textContent = t('search.button', '分析');
  }

  var _progressTimer = null;
  var _progressStart = 0;

  // 进度文案 — JS 内建字典，4 语言 × 4 阶段。不走 i18n JSON（模拟进度）
  var PROGRESS_TEXT = {
    zh: ['排队中 {n}', '获取商品信息', '生成分析报告', '即将完成...'],
    en: ['Queue {n}', 'Fetching details', 'Generating report', 'Almost done...'],
    vi: ['Xếp hàng {n}', 'Đang lấy thông tin', 'Đang tạo báo cáo', 'Sắp hoàn tất...'],
    th: ['รอคิว {n}', 'กำลังดึงข้อมูล', 'กำลังสร้างรายงาน', 'ใกล้เสร็จแล้ว...'],
    id: ['Antrian {n}', 'Mengambil data', 'Menyusun laporan', 'Hampir selesai...'],
  };

  var HINT_TEXT = {
    zh: ['1688 响应较慢，请耐心等待...', '仍在处理中，请勿刷新页面...'],
    en: ['1688 is responding slowly, please wait...', 'Still processing, please don\'t refresh...'],
    vi: ['1688 phản hồi chậm, vui lòng chờ...', 'Đang xử lý, vui lòng không làm mới...'],
    th: ['1688 ตอบสนองช้า กรุณารอสักครู่...', 'กำลังดำเนินการ กรุณาอย่ารีเฟรช...'],
    id: ['1688 merespons lambat, harap tunggu...', 'Sedang diproses, jangan refresh...'],
  };

  function _p(k) {
    var lang = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() : 'zh';
    var arr = k[lang] || k.zh;
    return arr;
  }

  var _queueNum = 0;
  var _queueLastRefresh = 0;

  // 4 阶段：索引→百分比→时间
  var PROGRESS_STAGES = [
    { idx: 0, pct: 5,   atMs: 0     },
    { idx: 1, pct: 30,  atMs: 8000  },
    { idx: 2, pct: 70,  atMs: 25000 },
    { idx: 3, pct: 90,  atMs: 45000 },
  ];

  function showProgress() {
    var el = document.getElementById('progressCard');
    var card = document.getElementById('productCard');
    var ring = document.getElementById('progressRing');
    if (el) el.style.display = 'block';
    if (card) card.style.display = 'none';
    if (ring) ring.classList.remove('done');

    _queueNum = Math.floor(Math.random() * 201) + 100;
    _queueLastRefresh = 0;
    _progressStart = Date.now();
    advanceProgress();
    _progressTimer = setInterval(advanceProgress, 2000);
  }

  function advanceProgress() {
    var elapsed = Date.now() - _progressStart;
    var bar = document.getElementById('progressBarFill');
    var statusEl = document.getElementById('progressStatus');
    var hintEl = document.getElementById('progressHint');

    var cur = PROGRESS_STAGES[0];
    for (var i = PROGRESS_STAGES.length - 1; i >= 0; i--) {
      if (elapsed >= PROGRESS_STAGES[i].atMs) { cur = PROGRESS_STAGES[i]; break; }
    }
    bar.style.width = cur.pct + '%';
    statusEl.textContent = _p(PROGRESS_TEXT)[cur.idx].replace('{n}', _queueNum);

    // 排队数字每 10s 刷新
    if (cur.idx === 0 && elapsed - _queueLastRefresh > 10000) {
      _queueNum = Math.floor(Math.random() * 201) + 100;
      _queueLastRefresh = elapsed;
    }

    // 超时提示
    var hints = _p(HINT_TEXT);
    if (elapsed > 90000)  hintEl.textContent = hints[1];
    else if (elapsed > 60000)  hintEl.textContent = hints[0];
  }

  function hideProgress() {
    clearInterval(_progressTimer);
    _progressTimer = null;
    var ring = document.getElementById('progressRing');
    var bar = document.getElementById('progressBarFill');
    if (ring) ring.classList.add('done');
    if (bar) bar.style.width = '100%';

    var el = document.getElementById('progressCard');
    if (el) el.style.display = 'none';

    if (_progressStart) {
      console.log('[⏱ 分析耗时] ' + ((Date.now() - _progressStart) / 1000).toFixed(1) + 's');
      _progressStart = 0;
    }
  }

  // ===== V2 渲染（display JSON → 纯赋值，无拼字符串、无硬编码中文） =====

  function renderV2(d) {
    // 标题
    var titleEl = document.querySelector('.prod-title');
    if (titleEl) { titleEl.textContent = d.title || ''; titleEl.title = d.titleOrig || ''; }

    // 价格：1688 原价 + 目标语言换算价
    var priceEl = document.querySelector('.prod-price');
    if (priceEl) {
      var p = d.price || {};
      var low = p.low ? '¥' + p.low : '';
      var high = p.high ? ' – ¥' + p.high : '';
      var u = p.unit ? ' / ' + p.unit : '';
      // 本地货币换算（当前页面语言决定）
      var local = _formatLocalPrice(p.low);
      var localStr = local ? ' <em class="price-local">≈ ' + local + '</em>' : '';
      var m = p.moq ? ' <span class="price-moq">' + t('report.moqLabel', '· MOQ ') + '<strong>' + p.moq + '</strong></span>' : '';
      var link = d.itemUrl ? ' <a href="' + d.itemUrl + '" target="_blank" class="price-link">' + t('report.1688Link', '1688 Page →') + '</a>' : '';
      priceEl.innerHTML = low + high + '<em>' + u + '</em>' + localStr + m + link;
    }

    // 信任条（纯赋值）
    var tb = d.trustBar || {};
    var el = document.querySelector('.tb-label'); if (el) el.textContent = tb.label || '';
    el = document.querySelector('.tb-sold'); if (el) el.textContent = tb.sold || '';
    el = document.querySelector('.tb-years'); if (el) el.textContent = tb.years || '';
    el = document.getElementById('tierStars');
    if (el) {
      el.textContent = (tb.stars && tb.tier) ? tb.stars + ' ' + tb.tier : '';
      el.title = tb.tierReason || '';
    }

    // Badge 行
    var badgeEl = document.querySelector('.badge-row');
    if (badgeEl) {
      var bArr = d.badges || [];
      badgeEl.innerHTML = bArr.length ? bArr.map(function (b) { return b.html; }).join(' ') : '';
      badgeEl.style.display = bArr.length ? '' : 'none';
    }

    // 规格
    var specEl = document.querySelector('.prod-specs');
    if (specEl) {
      var sArr = d.specs || [];
      specEl.innerHTML = sArr.length ? sArr.map(function (s) {
        return '<span class="spec-tag">' + s.name + ': ' + s.value + '</span>';
      }).join('') : '';
    }

    // 销售数据
    var sales = d.sales || {};
    var salesRow = document.querySelector('#tab-product .row');
    if (salesRow) {
      var sv = salesRow.querySelector('.row-value'); if (sv) sv.textContent = sales.sold || '';
      var se = salesRow.querySelector('.row-explain'); if (se) se.textContent = sales.explain || '';
    }

    // SKU
    var skuEl = document.querySelector('.sku-imgs');
    if (skuEl) {
      var skus = d.skus || [];
      skuEl.innerHTML = skus.length ? skus.slice(0, 6).map(function (s) {
        var imgUrl = s.imgUrl || '';
        var name = s.name || '';
        return '<img src="' + imgUrl + '" alt="' + name + '" title="' + name + '" referrerpolicy="no-referrer">';
      }).join('') : '';
    }

    // 阶梯价格
    var tbody = document.querySelector('.qp-table tbody');
    if (tbody) {
      var tiers = d.priceTiers || [];
      tbody.innerHTML = tiers.length ? tiers.map(function (t) {
        var range = t.qty_min != null ? (t.qty_min + (t.qty_max != null ? ('~' + t.qty_max) : '+')) : '-';
        return '<tr><td>' + range + '</td><td>' + (t.qty_min || '-') + '</td><td>¥' + (t.unit_price != null ? t.unit_price : '-') + '</td></tr>';
      }).join('') : '';
    }

    // 判词
    updateVerdict('tab-product', d.verdictProduct);
    updateVerdict('tab-factory', d.verdictFactory);
    updateVerdict('tab-sample', d.verdictSample);

    // 工厂信息
    var f = d.factory || {};
    var selV = document.getElementById('sellerVal'); if (selV) selV.textContent = f.sellerLabel || '';
    var selE = document.getElementById('sellerExp'); if (selE) selE.textContent = f.sellerExplain || '';
    var flgV = document.getElementById('flagsValue'); if (flgV) flgV.textContent = f.factoryFlags || '';
    var flgE = document.getElementById('flagsExplain'); if (flgE) flgE.textContent = f.flagsExplain || '';

    // 认证
    var certV = document.getElementById('certValue');
    var certE = document.getElementById('certExplain');
    var certL = document.getElementById('certReportLink');
    var shopL = document.getElementById('certShopLink');
    var shopS = document.getElementById('certShopSep');
    function _showCertLink(el) { if (el) el.style.display = ''; }
    function _hideCertLink(el) { if (el) el.style.display = 'none'; }
    if (certV) {
      if (f.certType) {
        certV.innerHTML = '<span class="cert-badge">🔖 ' + f.certType + '</span>';
        if (certE) certE.textContent = f.certExplain || '';
        if (f.certReportUrl && certL) { certL.href = f.certReportUrl; _showCertLink(certL); }
        else { _hideCertLink(certL); }
        if (shopL && f.shopUrl) {
          shopL.href = f.shopUrl; _showCertLink(shopL);
          if (shopS) shopS.style.display = (f.certReportUrl && certL) ? '' : 'none';
        } else { _hideCertLink(shopL); if (shopS) shopS.style.display = 'none'; }
      } else {
        certV.innerHTML = '<span style="font-size:var(--fs-xs);color:var(--ink-3);">' + t('report.noCertFallback', 'No Certification') + '</span>';
        _hideCertLink(certL);
        if (shopL && f.shopUrl) {
          if (certE) certE.textContent = f.certExplain || t('report.noCertExplainFallback', 'This supplier has not shown third-party certification.');
          shopL.href = f.shopUrl; _showCertLink(shopL);
          if (shopS) shopS.style.display = 'none';
        } else {
          if (certE) certE.textContent = f.certExplain || t('report.noCertExplainFallback', 'This supplier has not shown third-party certification.');
          _hideCertLink(shopL); if (shopS) shopS.style.display = 'none';
        }
      }
    }

    // 品类排名
    var rankRow = document.getElementById('row-rank');
    if (rankRow) {
      var rV = rankRow.querySelector('.row-value'); if (rV) rV.textContent = f.rankText || '';
      var rE = rankRow.querySelector('.row-explain'); if (rE) rE.textContent = f.rankExplain || '';
    }

    // 折叠区：公司名 + 地址
    var rowName = document.getElementById('row-name');
    if (rowName) {
      var nV = rowName.querySelector('.row-value'); if (nV) nV.textContent = f.supplierName || '';
      var nE = rowName.querySelector('.row-explain'); if (nE) nE.textContent = f.companyNameExplain || '';
    }
    var rowAddr = document.getElementById('row-addr');
    if (rowAddr) {
      var aV = rowAddr.querySelector('.row-value'); if (aV) aV.textContent = f.shippingLocation || '';
      var aE = rowAddr.querySelector('.row-explain'); if (aE) aE.textContent = f.industryCluster || '';
    }

    // 视频
    setVideoUrl(d.videoUrl || '');

    // 主图 + 缩略图
    var mainImg = document.getElementById('mainImg');
    var thumbCol = document.getElementById('thumbCol');
    if (d.images && d.images.length) {
      if (mainImg) mainImg.src = d.images[0];
      if (thumbCol) {
        var imgs = thumbCol.querySelectorAll('img');
        d.images.slice(0, 5).forEach(function (src, i) {
          if (imgs[i]) { imgs[i].src = src; imgs[i].dataset.full = src; if (i === 0) imgs[i].classList.add('active'); }
        });
      }
    }
  }

  // ===== 保存按钮 =====
  var saveBar = document.getElementById('saveBar');
  var saveBtn = document.getElementById('saveBtn');
  var currentOfferId = null;

  function showSaveBar(offerId) {
    if (!saveBar) return;
    currentOfferId = offerId;

    var user = checkAuth();
    if (!user) {
      saveBar.style.display = 'flex';
      saveBar.className = 'save-bar login-hint';
      saveBtn.textContent = t('report.saveBtn', '💾 Save');
      saveBtn.disabled = false;
      saveBtn.classList.remove('saved');
      saveBtn.onclick = function () {
        var returnPath = '/report.html?offerId=' + encodeURIComponent(currentOfferId);
        window.location.href = '/api/auth/google/login?redirect=' + encodeURIComponent(returnPath);
      };
      return;
    }

    var savedKey = 'saved_' + offerId;
    if (sessionStorage.getItem(savedKey)) {
      showSaved();
      return;
    }

    saveBar.style.display = 'flex';
    saveBar.className = 'save-bar';
    saveBtn.textContent = t('report.saveBtn', '💾 Save');
    saveBtn.disabled = false;
    saveBtn.classList.remove('saved');
    saveBtn.onclick = function () { doSave(); };
  }

  function showSaved() {
    saveBar.style.display = 'flex';
    saveBar.className = 'save-bar';
    saveBtn.textContent = t('report.savedBtn', '✓ Saved');
    saveBtn.disabled = true;
    saveBtn.classList.add('saved');
    saveBtn.onclick = null;
  }

  function doSave() {
    if (!currentOfferId) return;
    saveBtn.disabled = true;
    saveBtn.textContent = t('report.savingBtn', 'Saving...');

    API.saveReport(currentOfferId)
      .then(function (data) {
        if (data.code === 200) {
          sessionStorage.setItem('saved_' + currentOfferId, '1');
          showSaved();
          Messages.success('SAVE_OK', '保存成功！<br><small style="color:var(--ink-3)">可在历史记录中查看</small>');
        } else if (data.code === 409) {
          // 已达 20 条上限
          saveBtn.textContent = t('report.saveBtn', '💾 Save');
          saveBtn.disabled = false;
          Messages.warning('SAVE_LIMIT_EXCEEDED',
            '已达 20 条保存上限<br><small style="color:var(--ink-3)">请前往<a href="history.html" style="color:var(--brand);font-weight:600">历史记录</a>删除旧记录后再保存</small>');
        } else if (data.code === 410) {
          saveBtn.textContent = t('report.expiredBtn', '⚠ Expired');
          saveBtn.disabled = true;
        } else if (data.code === 401) {
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

  // ===== 渲染分析结果到页面 =====
  var productData = { priceMin: 7.5, moq: 2, unit: '把' };

  function renderResult(data) {
    hideProgress();
    var card = document.getElementById('productCard');
    if (card) card.style.display = 'block';

    var d = data.display || {};
    var p = d.price || {};

    // 费用计算从 display 取值（铁律：前端唯一数据源 = display）
    productData.priceMin = p.low || 0;
    productData.moq = p.moq || 2;
    productData.unit = p.unit || '';

    if (data.display) {
      renderV2(d);
    } else {
      // display 缺失时从 mapped 取判词（静态样例 JSON 未灌入 display 时的兜底）
      updateVerdict('tab-product', data.verdict_product || '');
      updateVerdict('tab-factory', data.verdict_factory || '');
      updateVerdict('tab-sample', data.verdict_sample || '');
    }

    updateCost();
    if (d.offerId) showSaveBar(d.offerId);
  }

  function updateVerdict(tabId, text) {
    if (!text) return;
    var panel = document.getElementById(tabId);
    if (!panel) return;
    var verdictEl = panel.querySelector('.verdict span:last-child');
    if (verdictEl) verdictEl.textContent = text;
  }

  // ===== 页面恢复 =====
  (function () {
    var lastTaskId = sessionStorage.getItem('lastTaskId');
    if (lastTaskId) {
      searchHint.textContent = t('report.resuming', 'Resuming unfinished analysis...');
      isSearching = true;
      showProgress();
      searchBtn.disabled = true;
      searchBtn.textContent = t('search.analyzing', 'Analyzing...');
      pollTask(lastTaskId, 0);
    }
  })();

  // ===== 静态样例加载（预生成 display JSON，和 live 分析同形状） =====
  (function () {
    var params = new URLSearchParams(window.location.search);
    var sample = params.get('sample');
    if (!sample) return;

    if (!/^[a-zA-Z0-9_-]+$/.test(sample)) {
      searchHint.textContent = t('report.sampleInvalid', 'Invalid sample parameter');
      return;
    }

    searchHint.textContent = t('report.sampleLoading', 'Loading sample data...');
    isSearching = true;
    showProgress();
    searchBtn.disabled = true;
    searchBtn.textContent = t('report.loading', 'Loading...');

    var lang = (typeof I18N !== 'undefined' && I18N.getLocale && I18N.getLocale()) || 'zh';
    if (['en','vi','th','id','zh'].indexOf(lang) === -1) lang = 'zh';

    fetch('/samples/' + sample + '/display_' + lang + '.json')
      .then(function (r) { return r.json(); })
      .catch(function () {
        if (lang !== 'en') return fetch('/samples/' + sample + '/display_en.json').then(function (r) { return r.json(); });
        throw new Error('Sample display not found');
      })
      .then(function (display) {
        var data = { display: display || {} };
        renderResult(data);
        if (display && display.offerId) {
          sessionStorage.setItem('lastResult_' + display.offerId, JSON.stringify(data));
        }
        updateCost();
        hideProgress();
        searchInput.value = display.itemUrl || '';
        isSearching = false;
        searchBtn.disabled = false;
        searchBtn.textContent = t('search.button', '分析');
        if (data.display && data.display.offerId) showSaveBar(data.display.offerId);
      })
      .catch(function (err) {
        console.warn('Sample load failed:', err);
        hideProgress();
        searchHint.textContent = t('report.sampleFailed', 'Sample failed to load, paste a link to search');
        isSearching = false;
        searchBtn.disabled = false;
        searchBtn.textContent = t('search.button', '分析');
      });
  })();

  // ===== URL 参数自动分析（Bug #1：优先查 DB，Apify 兜底） =====
  (function () {
    if (sessionStorage.getItem('lastTaskId')) return;

    var params = new URLSearchParams(window.location.search);
    var sample = params.get('sample');
    var offerId = params.get('offerId');
    var urlParam = params.get('url');

    if (sample) return;
    if (!offerId && !urlParam) return;

    // 提取 lookupId（offerId 参数 或 url 参数中抽取）
    var lookupId = offerId;
    if (!lookupId && urlParam) {
      var m = decodeURIComponent(urlParam).match(/offer(?:Id)?[=/](\d+)/i);
      lookupId = m ? m[1] : null;
    }

    if (lookupId) {
      // 1. sessionStorage 缓存 → 秒恢复（如登录跳转回来）
      var savedResult = sessionStorage.getItem('lastResult_' + lookupId);
      if (savedResult) {
        try {
          var cached = JSON.parse(savedResult);
          renderResult(cached);
          updateCost();
          searchInput.value = cached.itemUrl || (offerId ? 'https://detail.1688.com/offer/' + offerId + '.html' : decodeURIComponent(urlParam));
          searchHint.textContent = t('report.restored', '已恢复之前的数据 — 每日免费 3 次');
          searchBtn.disabled = false;
          searchBtn.textContent = t('search.button', '分析');
          return;
        } catch (e) { /* JSON 损坏，走正常流程 */ }
      }

      // 2. 已登录 → 优先查 DB（Bug #1：历史→report 秒出，不走 Apify）
      var user = checkAuth();
      if (user) {
        isSearching = true;
        showProgress();
        searchBtn.disabled = true;
        searchBtn.textContent = t('report.loading', 'Loading...');
        searchHint.textContent = t('report.dbLoadingHint', 'Loading saved analysis...');

        var currentLang = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() : '';
        API.getReport(lookupId, currentLang)
          .then(function (data) {
            if (data && data.code === 200 && data.data && data.data.status === 'done' && data.data.result) {
              renderResult(data.data.result);
              updateCost();
              searchInput.value = data.data.result.itemUrl || 'https://detail.1688.com/offer/' + lookupId + '.html';
              searchHint.textContent = t('report.dbLoadedHint', 'Saved analysis data');
              hideProgress();
              resetSearchButton();
              sessionStorage.setItem('lastResult_' + lookupId, JSON.stringify(data.data.result));
            } else {
              // DB 无记录（可能已被删除）→ 清除保存标记，回退到 Apify
              sessionStorage.removeItem('saved_' + lookupId);
              startFromUrl(offerId, urlParam);
            }
          })
          .catch(function () {
            // 网络/服务异常 → 清除保存标记，回退到 Apify
            sessionStorage.removeItem('saved_' + lookupId);
            startFromUrl(offerId, urlParam);
          });
        return;
      }

      // 3. 未登录 → 直接走 Apify
      startFromUrl(offerId, urlParam);
    } else {
      // lookupId 为空（url 参数解析不出 offerId）→ 直接用原 URL 分析
      startFromUrl(offerId, urlParam);
    }

    function startFromUrl(offerIdParam, urlParamVal) {
      var targetUrl = offerIdParam
        ? 'https://detail.1688.com/offer/' + offerIdParam + '.html'
        : decodeURIComponent(urlParamVal);

      searchInput.value = targetUrl;
      searchHint.textContent = t('report.analyzing', '分析中...');
      isSearching = true;
      showProgress();
      searchBtn.disabled = true;
      searchBtn.textContent = t('search.analyzing', 'Analyzing...');
      startAnalysis(targetUrl);
    }
  })();

  // ===== 国际运费表 =====
  var shipRates = {
    VN: { eco: [3, 5],  label: '🚛 陆运', days: '4-7天', exp: [7, 12], expLabel: '✈️ 空运', expDays: '2-3天' },
    TH: { eco: [5, 8],  label: '🚛 陆运', days: '5-7天', exp: [8, 15], expLabel: '✈️ 空运', expDays: '3-5天' },
    ID: { eco: [10, 18], label: '✈️ 空运', days: '5-10天', exp: null, expLabel: null, expDays: null },
    MY: { eco: [5, 8],  label: '🚛 陆运', days: '5-7天', exp: [8, 14], expLabel: '✈️ 空运', expDays: '3-5天' },
    PH: { eco: [10, 16], label: '✈️ 空运', days: '7-10天', exp: null, expLabel: null, expDays: null }
  };

  var USD_RATE = 7.2;  // 默认值，页面加载后从 /api/config 更新
  var SERVICE_FEE = 10;
  var DOMESTIC_FREIGHT = 10;

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

  // 从后端取汇率（独立于 i18n.js，不依赖语言检测功能）
  if (typeof API !== 'undefined' && API.getConfig) {
    API.getConfig().then(function (res) {
      if (res && res.data && res.data.cnyUsdRate) {
        USD_RATE = res.data.cnyUsdRate;
        updateCost();
      }
    }).catch(function () { /* 保持默认值 */ });
  }

  var qtyVal = document.getElementById('qtyVal');
  var qtyMinus = document.getElementById('qtyMinus');
  var qtyPlus = document.getElementById('qtyPlus');
  var productFeeEl = document.getElementById('productFee');
  var domesticFeeEl = document.getElementById('domesticFee');
  var depositTotalEl = document.getElementById('depositTotal');
  var shipFeeValEl = document.getElementById('shipFeeVal');
  var shipMetaEl = document.getElementById('shipMeta');
  var balanceTotalEl = document.getElementById('balanceTotal');
  var totalFeeEl = document.getElementById('totalFee');

  var qty = productData.moq;

  function updateCost() {
    var cny = productData.priceMin * qty;
    var usd = cny / USD_RATE;
    var domUsd = DOMESTIC_FREIGHT / USD_RATE;
    var depCny = cny + DOMESTIC_FREIGHT;
    var depUsd = depCny / USD_RATE;

    if (productFeeEl) productFeeEl.textContent = '¥' + cny.toFixed(2) + ' ≈ ' + I18N.formatPrice(usd);
    if (domesticFeeEl) domesticFeeEl.textContent = '¥' + DOMESTIC_FREIGHT.toFixed(2) + ' ≈ ' + I18N.formatPrice(domUsd);
    if (depositTotalEl) depositTotalEl.textContent = '¥' + depCny.toFixed(2) + ' ≈ ' + I18N.formatPrice(depUsd);

    var loc = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() : 'en';
    var DEST_MAP = { vi: 'VN', th: 'TH', id: 'ID' };
    var dest = DEST_MAP[loc] || 'VN';
    var ship = shipRates[dest];
    if (shipFeeValEl) shipFeeValEl.textContent = I18N.formatPriceRange(ship.eco[0], ship.eco[1]);
    var isLand = ship.label && ship.label.indexOf('陆运') >= 0;
    var methodLabel = isLand ? t('ship.landLabel', '🚛 Land') : t('ship.airLabel', '✈️ Air');
    if (shipMetaEl) shipMetaEl.textContent = methodLabel + ' ' + ship.days + ', ' + t('ship.weightNote', 'Based on weight/volume');

    var balLow = ship.eco[0] + SERVICE_FEE;
    var balHigh = ship.eco[1] + SERVICE_FEE;
    if (balanceTotalEl) balanceTotalEl.textContent = I18N.formatPriceRange(balLow, balHigh);

    var totalLow = depUsd + ship.eco[0] + SERVICE_FEE;
    var totalHigh = depUsd + ship.eco[1] + SERVICE_FEE;
    if (totalFeeEl) totalFeeEl.textContent = I18N.formatPriceRange(totalLow, totalHigh);
  }

  qtyMinus.addEventListener('click', function () {
    if (qty > productData.moq) { qty--; qtyVal.textContent = qty; updateCost(); }
  });
  qtyPlus.addEventListener('click', function () {
    if (qty < 50) { qty++; qtyVal.textContent = qty; updateCost(); }
  });
  // ===== 折叠/展开 =====
  document.getElementById('factoryDetailToggle').addEventListener('click', function () {
    var d = document.getElementById('factoryDetail');
    var expanded = d.style.display !== 'none';
    if (expanded) {
      d.style.display = 'none';
      this.textContent = t('report.companyInfo', '📋 Company Info ▾');
    } else {
      d.style.display = 'block';
      this.textContent = t('report.companyInfoCollapse', '📋 Company Info ▴');
    }
  });

  document.getElementById('inspectToggle').addEventListener('click', function () {
    var d = document.getElementById('inspectDetail');
    if (d.style.display === 'none') { d.style.display = 'block'; this.classList.add('active'); }
    else { d.style.display = 'none'; this.classList.remove('active'); }
  });

  // ===== 缩略图切主图 =====
  var mainImg = document.getElementById('mainImg');
  var thumbVideo = document.getElementById('thumbVideo');
  var videoUrl = '';
  function setVideoUrl(url) {
    videoUrl = url || '';
    if (thumbVideo) thumbVideo.style.display = videoUrl ? '' : 'none';
  }

  document.querySelectorAll('#thumbCol img').forEach(function (thumb) {
    thumb.addEventListener('click', function () {
      document.querySelectorAll('#thumbCol img').forEach(function (t) { t.classList.remove('active'); });
      this.classList.add('active');
      mainImg.src = this.dataset.full;
      mainImg.style.display = 'block';
      var oldV = mainImg.parentNode.querySelector('video');
      if (oldV) oldV.remove();
    });
  });

  thumbVideo.addEventListener('click', function () {
    var wrap = mainImg.parentNode;
    var oldV = wrap.querySelector('video');
    if (oldV) oldV.remove();
    mainImg.style.display = 'none';
    var v = document.createElement('video');
    v.src = videoUrl;
    v.controls = true;
    v.style.width = '100%';
    v.style.borderRadius = '12px';
    v.style.background = '#000';
    v.play();
    wrap.appendChild(v);
    document.querySelectorAll('#thumbCol img').forEach(function (t) { t.classList.remove('active'); });
  });

  // ===== Tab 切换 =====
  document.querySelectorAll('.tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
      document.querySelectorAll('.panel').forEach(function (p) { p.classList.remove('active'); });
      this.classList.add('active');
      document.getElementById('tab-' + this.dataset.tab).classList.add('active');
    });
  });

  // ===== 初始化 =====
  updateCost();
  Share.bindEvents();
  var shareBtn = document.getElementById('shareBtnMain');
  if (shareBtn) shareBtn.textContent = t('report.shareBtn', '📤 Share');

  // Bug #14：页面离开时清理轮询定时器
  window.addEventListener('beforeunload', function () {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }
  });

})();

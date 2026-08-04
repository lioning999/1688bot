// ===== inspect.js — 1688 验货报告页 =====
// 依赖：api/core.js, utils/i18n.js, utils/components.js, utils/messages.js
(function () {
  'use strict';

  function t(key, fallback) {
    return (typeof I18N !== 'undefined' && I18N.t) ? (I18N.t(key) || fallback) : fallback;
  }

  // ===== 常量 =====
  var SAMPLE_MOQ = 2;
  var SAMPLE_PRICE = 2.00;
  var SAMPLE_DOMESTIC = 10.00;
  var SAMPLE_SERVICE = 10.00;
  var USD_RATE = 7.14;
  var RATES = { CNY: 1, USD: 0.14, VND: 3500, IDR: 2200, THB: 5.0 };
  var SYMBOLS = { CNY: '¥', USD: '$', VND: '₫', IDR: 'Rp', THB: '฿' };

  var sampleQty = 2;

  // ===== 初始化 =====
  function init() {
    var params = new URLSearchParams(window.location.search);
    var sample = params.get('sample');
    var url = params.get('url');

    if (sample) {
      loadSample(sample);
    } else if (url) {
      startAnalysis(url);
    } else {
      // 尝试恢复未完成的分析
      var lastTaskId = sessionStorage.getItem('lastTaskId');
      if (lastTaskId) {
        startPolling(lastTaskId);
      } else {
        showError(t('inspect.noUrl', 'No product URL provided'), t('inspect.noUrlHint', 'Please search from the homepage.'));
      }
    }
  }

  // ===== API 调用 =====
  function startAnalysis(url) {
    var lang = (typeof I18N !== 'undefined' && I18N.getLocale) ? I18N.getLocale() : '';
    API.analyze(url, lang)
      .then(function (data) {
        if (data.code !== 200) {
          hideSkeleton();
          showError(data.message || t('inspect.startFailed', 'Analysis failed to start'),
                    t('inspect.retryHint', 'Please return to the homepage and try again.'));
          return;
        }
        var taskId = data.data && data.data.task_id;
        if (!taskId) {
          hideSkeleton();
          showError(t('inspect.noTaskId', 'No task ID returned'), '');
          return;
        }
        sessionStorage.setItem('lastTaskId', taskId);
        startPolling(taskId);
      })
      .catch(function (err) {
        hideSkeleton();
        showError(t('inspect.networkError', 'Network error, please retry'), '');
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
      showError(t('inspect.timeout', 'Analysis timed out'), t('inspect.timeoutHint', 'Please try again later.'));
      return;
    }

    API.getTask(taskId)
      .then(function (data) {
        var task = data.data;
        if (!task) {
          hideSkeleton();
          sessionStorage.removeItem('lastTaskId');
          showError(t('inspect.taskExpired', 'Task expired'), '');
          return;
        }

        if (task.status === 'done') {
          sessionStorage.removeItem('lastTaskId');
          renderResult(task.result);
          if (task.result && task.result.offerId) {
            sessionStorage.setItem('lastResult_' + task.result.offerId, JSON.stringify(task.result));
          }
          if (task.warning) Messages.warning(task.warning_msg_code || 'STALE_DATA', task.warning);
        } else if (task.status === 'failed') {
          hideSkeleton();
          sessionStorage.removeItem('lastTaskId');
          showError(task.error || t('inspect.analysisFailed', 'Analysis failed'),
                    t('inspect.retryHint', 'Please return to the homepage and try again.'));
        } else {
          setTimeout(function () { pollTask(taskId, attempt + 1); }, 2000);
        }
      })
      .catch(function (err) {
        hideSkeleton();
        sessionStorage.removeItem('lastTaskId');
        showError(t('inspect.networkError', 'Network error'), '');
        console.warn('inspect: poll failed:', err);
      });
  }

  // ===== 静态样例 =====
  function loadSample(sample) {
    if (!/^[a-zA-Z0-9_-]+$/.test(sample)) {
      hideSkeleton();
      showError(t('inspect.invalidSample', 'Invalid sample'), '');
      return;
    }

    var lang = (typeof I18N !== 'undefined' && I18N.getLocale && I18N.getLocale()) || 'zh';
    if (['en','vi','th','id','zh'].indexOf(lang) === -1) lang = 'zh';

    fetch('/samples/' + sample + '/display_' + lang + '.json')
      .then(function (r) { return r.json(); })
      .catch(function () {
        if (lang !== 'en') return fetch('/samples/' + sample + '/display_en.json').then(function (r) { return r.json(); });
        throw new Error('Sample not found');
      })
      .then(function (display) {
        renderResult({ display: display || {} });
        if (display && display.offerId) {
          sessionStorage.setItem('lastResult_' + display.offerId, JSON.stringify({ display: display }));
        }
      })
      .catch(function () {
        hideSkeleton();
        showError(t('inspect.sampleNotFound', 'Sample data not found'), '');
      });
  }

  // ===== 主渲染 =====
  function renderResult(data) {
    hideSkeleton();
    var content = document.getElementById('inspectContent');
    if (content) content.style.display = '';

    var d = data.display || {};
    var p = d.price || {};

    // 费用计算参数
    SAMPLE_PRICE = p.low || 2;
    SAMPLE_MOQ = p.moq || 2;
    sampleQty = SAMPLE_MOQ;
    document.getElementById('qtyVal').textContent = sampleQty;

    renderProduct(d);
    renderSummary(d);
    renderEval(d);
    renderSample(d);

    updateCost();
    initTreeState(d);

    if (d.offerId) showSaveBar(d.offerId);
  }

  // ===== ① 商品确认 =====
  function renderProduct(d) {
    // 标题
    var titleEl = document.getElementById('prodTitle');
    if (titleEl) { titleEl.textContent = d.title || ''; titleEl.title = d.titleOrig || ''; }

    // 价格行
    var priceEl = document.getElementById('prodPrice');
    if (priceEl) {
      var p = d.price || {};
      var lowStr = p.low ? '¥' + p.low : '';
      var highStr = p.high ? ' – ¥' + p.high : '';
      var unitStr = p.unit ? ' / ' + p.unit : '';
      var moqStr = p.moq ? ' <span class="price-moq">📦 ' + t('report.moqLabel', 'MOQ') + ' <strong>' + p.moq + '</strong></span>' : '';
      var linkStr = d.itemUrl ? ' <a href="' + d.itemUrl + '" target="_blank" class="price-link">' + t('report.1688Link', '1688 Page →') + '</a>' : '';
      priceEl.innerHTML = lowStr + highStr + '<em>' + unitStr + '</em>' + moqStr + linkStr;
    }

    // Badge 行
    var badgeEl = document.getElementById('badgeRow');
    if (badgeEl) {
      var bArr = d.badges || [];
      badgeEl.innerHTML = bArr.length ? bArr.map(function (b) { return b.html || ''; }).join(' ') : '';
      badgeEl.style.display = bArr.length ? '' : 'none';
    }

    // 信任条
    var tb = d.trustBar || {};
    var trustEl = document.getElementById('trustBar');
    if (trustEl) {
      var labelStr = tb.label ? '<span class="tb-label">' + tb.label + '</span>' : '';
      var soldStr = tb.sold ? '<span class="tb-sold">' + tb.sold + '</span>' : '';
      var yearsStr = tb.years ? '<span class="tb-years">' + tb.years + '</span>' : '';
      var starsStr = (tb.stars && tb.tier) ? '<span class="tier-stars">' + tb.stars + ' ' + tb.tier + '</span>' : '';
      trustEl.innerHTML = labelStr + soldStr + yearsStr + starsStr;
      trustEl.style.display = (labelStr || soldStr || yearsStr) ? '' : 'none';
    }

    // 库存
    var stockEl = document.getElementById('stockStatus');
    if (stockEl) {
      var inv = d.inventory || {};
      if (inv.status === 'ok') {
        stockEl.className = 'stock-status ok';
        stockEl.textContent = '📦 ' + (inv.text || t('inspect.stockOk', 'Sufficient stock')) + ' ✅';
      } else if (inv.status === 'warn') {
        stockEl.className = 'stock-status warn';
        stockEl.textContent = '📦 ' + (inv.text || t('inspect.stockWarn', 'Low stock')) + ' ⚠️';
      } else {
        stockEl.className = 'stock-status warn';
        stockEl.textContent = '📦 ' + (inv.text || t('inspect.stockUnknown', 'Stock not disclosed')) + ' ⚠️';
      }
    }

    // 图片
    var mainImg = document.getElementById('mainImg');
    var thumbCol = document.getElementById('thumbCol');
    if (d.images && d.images.length) {
      if (mainImg) mainImg.src = d.images[0];
      if (thumbCol) {
        var html = '';
        d.images.slice(0, 5).forEach(function (src, i) {
          html += '<img src="' + src + '" alt="图' + (i + 1) + '" referrerpolicy="no-referrer"' +
                  (i === 0 ? ' class="active"' : '') +
                  ' onclick="document.getElementById(\'mainImg\').src=this.src" loading="lazy">';
        });
        thumbCol.innerHTML = html;
      }
    }
  }

  // ===== ② 综合结论 =====
  function renderSummary(d) {
    // summaryLine 来自新 evaluator，verdictProduct 来自旧 evaluator——优先用新的
    var summaryText = d.summaryLine || d.verdictProduct || '';
    var summaryMeta = '';
    var tier = 'none';

    // 从 productEval/supplierEval 取分（新字段优先），否则从 trustBar 推断
    var pScore = (d.productEval && d.productEval.score != null) ? d.productEval.score : null;
    var sGrade = (d.supplierEval && d.supplierEval.grade) ? d.supplierEval.grade : '';
    var sScore = (d.supplierEval && d.supplierEval.score != null) ? d.supplierEval.score : null;

    // 推断档位
    if (pScore != null && sScore != null) {
      if (pScore === 0 && sScore === 0) tier = 'none';
      else if (pScore >= 7 && sScore >= 7) tier = 'go';
      else if (pScore <= 3 && sScore <= 3) tier = 'bad';
      else tier = 'ok';
    } else {
      // 从旧字段推断
      var tb = d.trustBar || {};
      if (tb.tier === 'sufficient') tier = 'go';
      else if (tb.tier === 'partial') tier = 'ok';
      else if (tb.tier === 'limited') tier = 'bad';
    }

    // 一行摘要
    if (pScore != null) summaryMeta += '📦' + t('inspect.productScore', '货品') + ' ' + pScore + t('inspect.scoreUnit', '分');
    if (sGrade) summaryMeta += (summaryMeta ? ' · ' : '') + '🏭' + sGrade;
    if (sScore != null) summaryMeta += ' ' + sScore + '/9' + t('inspect.scoreUnit', '分');
    if (!summaryMeta && d.trustBar) {
      // 兜底：从 trustBar 拼
      var tb2 = d.trustBar || {};
      summaryMeta = '📦' + (tb2.label || '') + ' · 🏭' + (tb2.tier || '');
    }

    // 渲染 verdict
    var verdictEl = document.getElementById('summaryVerdict');
    if (verdictEl) {
      verdictEl.className = 'verdict summary-' + tier;
      var headlineEl = document.getElementById('summaryHeadline');
      var subEl = document.getElementById('summarySub');
      var tierEmoji = { go: '🟢', ok: '🟡', bad: '🔴', none: '⬜' };
      var tierLabel = {
        go: t('inspect.tierGo', '推荐拿样'),
        ok: t('inspect.tierOk', '可以考虑'),
        bad: t('inspect.tierBad', '谨慎评估'),
        none: t('inspect.tierNone', '无法判断')
      };
      if (headlineEl) headlineEl.textContent = tierEmoji[tier] + ' ' + tierLabel[tier];
      if (subEl) subEl.textContent = summaryText;
    }

    // 注意事项精简版
    var cautions = d.cautions || [];
    var cautionsMiniEl = document.getElementById('cautionsMini');
    if (cautionsMiniEl && cautions.length > 0) {
      cautionsMiniEl.style.display = '';
      cautionsMiniEl.innerHTML = cautions.slice(0, 2).map(function (c) {
        return '<div class="caution-mini">⚠️ ' + (typeof c === 'string' ? c : (c.text || c.summary || '')) + '</div>';
      }).join('');
    }

    // 一行摘要
    var metaEl = document.getElementById('summaryMeta');
    if (metaEl) metaEl.textContent = summaryMeta;
  }

  // ===== ③ 分项论据 =====
  function renderEval(d) {
    renderProductEval(d);
    renderSupplierEval(d);
    renderCautions(d);
    renderProfit(d);
  }

  // ③📦 货品验证
  function renderProductEval(d) {
    var pe = d.productEval || {};
    var score = pe.score;
    var labels = pe.labels || [];
    var dataRows = pe.data_rows || pe.dataRows || [];
    var human = pe.human || '';

    // 如果无 evaluator 数据，从旧字段构建
    if (score == null && !human) {
      // 兜底：从 verdictProduct 提取
      human = d.verdictProduct || '';
      score = (d.trustBar && d.trustBar.tier === 'sufficient') ? 12 :
              (d.trustBar && d.trustBar.tier === 'partial') ? 6 : 3;
    }

    var tierClass = score >= 10 ? 'go' : score >= 4 ? 'ok' : score > 0 ? 'bad' : 'none';
    var scoreText = score != null ? score + '/12' + t('inspect.scoreUnit', '分') : '—';
    var subText = score >= 12 ? t('inspect.perfect', '满分') :
                  score >= 10 ? t('inspect.excellent', '优秀') : '';

    // Badge
    var badgeEl = document.getElementById('productScoreBadge');
    if (badgeEl) {
      badgeEl.textContent = scoreText;
      badgeEl.className = 'tree-badge ' + tierClass;
    }
    var subEl = document.getElementById('productScoreSub');
    if (subEl) subEl.textContent = subText;

    // 维度行
    var bodyEl = document.getElementById('productBody');
    if (bodyEl) {
      var html = '';
      if (dataRows.length > 0) {
        dataRows.forEach(function (row) {
          html += '<div class="eval-dim">' +
            '<span class="eval-dim-label">' + (row.label || '') + '</span>' +
            '<span class="eval-dim-data">' + (row.value || '') + '</span>' +
            '<span class="eval-dim-tier">' + (row.tier || '') + '</span>' +
            '<span class="eval-dim-ref">' + (row.ref || '') + '</span>' +
            '</div>';
        });
      }
      // 补充信息
      if (d.factory && d.factory.rankText) {
        html += '<div class="eval-extra">🏆 ' + d.factory.rankText + '</div>';
      }
      // 组尾人话
      if (human) {
        html += '<div class="eval-human ' + tierClass + '">💬 ' + human + '</div>';
      }
      bodyEl.innerHTML = html;
    }

    // 预览
    var previewEl = document.getElementById('productPreview');
    if (previewEl) {
      previewEl.textContent = human ? human.substring(0, 40) + (human.length > 40 ? '...' : '') : '';
    }
  }

  // ③🏭 供应商资质
  function renderSupplierEval(d) {
    var se = d.supplierEval || {};
    var score = se.score;
    var grade = se.grade || '';
    var labels = se.labels || [];
    var dataRows = se.data_rows || [];
    var human = se.human || '';

    // 兜底
    if (score == null && !human) {
      human = d.verdictFactory || '';
      grade = (d.trustBar && d.trustBar.label) ? d.trustBar.label : '';
      var tb = d.trustBar || {};
      score = tb.tier === 'sufficient' ? 9 : tb.tier === 'partial' ? 5 : 2;
    }

    var tierClass = score >= 7 ? 'go' : score >= 4 ? 'ok' : score > 0 ? 'bad' : 'none';
    var scoreText = score != null ? score + '/9' + t('inspect.scoreUnit', '分') : '—';

    // Grade badge
    var gradeEl = document.getElementById('supplierGradeBadge');
    if (gradeEl && grade) {
      gradeEl.textContent = grade;
      gradeEl.className = 'tree-badge ' + tierClass;
      gradeEl.style.display = '';
    } else if (gradeEl) {
      gradeEl.style.display = 'none';
    }
    // Score badge
    var scoreBadgeEl = document.getElementById('supplierScoreBadge');
    if (scoreBadgeEl) {
      scoreBadgeEl.textContent = scoreText;
      scoreBadgeEl.className = 'tree-badge ' + tierClass;
    }

    // 维度行
    var bodyEl = document.getElementById('supplierBody');
    if (bodyEl) {
      var html = '';
      if (dataRows.length > 0) {
        dataRows.forEach(function (row) {
          html += '<div class="eval-dim">' +
            '<span class="eval-dim-label">' + (row.label || '') + '</span>' +
            '<span class="eval-dim-data">' + (row.value || '') + '</span>' +
            '<span class="eval-dim-tier">' + (row.tier || '') + '</span>' +
            '<span class="eval-dim-ref">' + (row.ref || '') + '</span>' +
            '</div>';
        });
      }
      // 平台标签
      if (d.factory && d.factory.factoryFlags) {
        html += '<div class="badge-row" style="margin-top:var(--s2);">' +
          '<span class="badge-sm blue">' + d.factory.factoryFlags + '</span>' +
          '</div>';
      }
      // 组尾人话
      if (human) {
        html += '<div class="eval-human ' + tierClass + '">💬 ' + human + '</div>';
      }
      bodyEl.innerHTML = html;
    }

    // 预览
    var previewEl = document.getElementById('supplierPreview');
    if (previewEl) {
      previewEl.textContent = human ? human.substring(0, 40) + (human.length > 40 ? '...' : '') : '';
    }
  }

  // ③⚠️ 风险提示
  function renderCautions(d) {
    var cautions = d.cautions || [];
    var hasRisk = cautions.length > 0;

    var badgeEl = document.getElementById('riskBadge');
    if (badgeEl) {
      if (hasRisk) {
        badgeEl.textContent = cautions.length + t('inspect.riskItems', ' 项风险');
        badgeEl.className = 'tree-badge ok';
      } else {
        badgeEl.textContent = t('inspect.noRisk', '无风险');
        badgeEl.className = 'tree-badge go';
      }
    }

    var previewEl = document.getElementById('riskPreview');
    var bodyEl = document.getElementById('riskBody');

    if (hasRisk) {
      if (previewEl) {
        previewEl.textContent = cautions.map(function (c) {
          return typeof c === 'string' ? c.substring(0, 30) : ((c.summary || c.text || '').substring(0, 30));
        }).join(' · ');
      }
      if (bodyEl) {
        bodyEl.innerHTML = cautions.map(function (c) {
          var text = typeof c === 'string' ? c : (c.text || '');
          var detail = typeof c === 'object' ? (c.detail || '') : '';
          return '<div class="warn" style="margin-bottom:var(--s2);">' +
            (text ? '<strong>' + text + '</strong>' : '') +
            (detail ? '<div style="margin-top:var(--s1);font-size:var(--fs-xs);color:var(--ink-2);">' + detail + '</div>' : '') +
            '</div>';
        }).join('');
      }
    } else {
      if (previewEl) previewEl.textContent = '✅ ' + t('inspect.riskClear', '未发现明显风险');
      if (bodyEl) {
        bodyEl.innerHTML = '<div class="eval-clear">✅ ' + t('inspect.riskClear', '未发现明显风险') + '</div>';
      }
    }
  }

  // ③💰 利润空间
  function renderProfit(d) {
    var previewEl = document.getElementById('profitPreview');
    var bodyEl = document.getElementById('profitBody');
    var p = d.price || {};

    if (previewEl) {
      previewEl.textContent = t('inspect.profitPreview', '展开计算利润空间');
    }

    if (bodyEl) {
      var tiers = d.priceTiers || [];
      var tierHtml = '';
      if (tiers.length > 0) {
        tierHtml = '<table class="qp-table"><thead><tr>' +
          '<th data-i18n="report.qtyRange">Qty</th>' +
          '<th data-i18n="report.moqHeader">MOQ</th>' +
          '<th data-i18n="report.unitPrice">Price (CNY)</th></tr></thead><tbody>' +
          tiers.map(function (t2) {
            var range = t2.qty_min != null ? (t2.qty_min + (t2.qty_max != null ? ('~' + t2.qty_max) : '+')) : '-';
            return '<tr><td>' + range + '</td><td>' + (t2.qty_min || '-') + '</td><td>¥' + (t2.unit_price != null ? t2.unit_price : '-') + '</td></tr>';
          }).join('') + '</tbody></table>';
      }

      bodyEl.innerHTML = tierHtml +
        '<div class="currency-bar" style="margin-top:var(--s3);">' +
        '💱 <span style="font-size:var(--fs-xs);">' + t('inspect.currency', 'Currency') + ':</span>' +
        '<select id="currency" onchange="window._inspectCalcProfit()" style="padding:4px 8px;border:1px solid var(--line);border-radius:6px;font-size:12px;background:var(--paper-2);color:var(--ink);">' +
        '<option value="USD">USD $</option>' +
        '<option value="CNY">CNY ¥</option>' +
        '<option value="VND">VND ₫</option>' +
        '<option value="IDR">IDR Rp</option>' +
        '<option value="THB">THB ฿</option>' +
        '</select>' +
        '<span class="rate-hint" id="rateHint" style="font-size:10px;color:var(--ink-3);">1 CNY ≈ $0.14</span>' +
        '</div>' +
        '<div class="profit-inputs" style="display:flex;gap:10px;">' +
        '<div class="cf-field">' +
        '<label>' + t('inspect.sellPrice', 'Est. Local Sell Price (¥)') + '</label>' +
        '<input type="number" placeholder="15" value="15" id="sellPrice" oninput="window._inspectCalcProfit()" ' +
        'style="width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:var(--r-sm);font-size:14px;background:var(--paper);color:var(--ink);">' +
        '</div>' +
        '<div class="cf-field">' +
        '<label>' + t('inspect.shipping', 'Est. Intl Freight (¥/pc)') + '</label>' +
        '<input type="number" placeholder="3" value="3" id="shipping" oninput="window._inspectCalcProfit()" ' +
        'style="width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:var(--r-sm);font-size:14px;background:var(--paper);color:var(--ink);">' +
        '</div>' +
        '</div>' +
        '<div class="eval-human go" id="profitResult" style="margin-top:var(--s3);">' +
        '<span style="font-size:var(--fs-xs);">' + t('inspect.calcBased', 'Based on MOQ of') + ' <b id="profitMoq">' + SAMPLE_MOQ + '</b> ' + t('inspect.units', 'pcs') + ' —</span><br>' +
        t('inspect.margin', 'Margin') + ' <span style="font-size:20px;font-weight:700;" id="marginRate">—</span><br>' +
        t('inspect.perProfit', 'Profit/pc') + ' <span id="perProfit">—</span> · ' +
        t('inspect.batchProfit', 'Batch profit') + ' <span id="batchProfit">—</span>' +
        '<div id="profitCny" style="font-size:10px;color:var(--ink-2);margin-top:2px;"></div>' +
        '</div>';
    }
  }

  // ===== ④ 拿样发货 =====
  function renderSample(d) {
    // 数量选择事件绑定
    document.getElementById('qtyMinus').addEventListener('click', function () {
      if (sampleQty > SAMPLE_MOQ) { sampleQty--; updateCost(); }
    });
    document.getElementById('qtyPlus').addEventListener('click', function () {
      if (sampleQty < 50) { sampleQty++; updateCost(); }
    });

    updateCost();
  }

  // ===== 费用计算 =====
  function updateCost() {
    document.getElementById('qtyVal').textContent = sampleQty;
    document.getElementById('qtyMinus').disabled = (sampleQty <= SAMPLE_MOQ);

    var productCny = SAMPLE_PRICE * sampleQty;
    var depositCny = productCny + SAMPLE_DOMESTIC;
    var shipLow = 3, shipHigh = 5;
    var totalLow = depositCny / USD_RATE + shipLow + SAMPLE_SERVICE;
    var totalHigh = depositCny / USD_RATE + shipHigh + SAMPLE_SERVICE;

    document.getElementById('productFee').textContent = '¥' + productCny.toFixed(2);
    document.getElementById('depositTotal').textContent = '¥' + depositCny.toFixed(2) + ' ≈ $' + (depositCny / USD_RATE).toFixed(2);
    document.getElementById('totalFee').textContent = '$' + Math.round(totalLow) + ' – $' + Math.round(totalHigh);
  }

  // ===== 利润计算（挂 window 给 oninput 回调用） =====
  window._inspectCalcProfit = function () {
    var sellPriceCny = parseFloat(document.getElementById('sellPrice').value) || 0;
    var shippingCny = parseFloat(document.getElementById('shipping').value) || 0;
    var costPrice = SAMPLE_PRICE;
    var moq = SAMPLE_MOQ;

    var perProfitCny = sellPriceCny - costPrice - shippingCny;
    var margin = sellPriceCny > 0 ? ((perProfitCny / sellPriceCny) * 100) : 0;
    var batchProfitCny = perProfitCny * moq;

    var cur = document.getElementById('currency').value;
    var rate = RATES[cur];
    var sym = SYMBOLS[cur];

    document.getElementById('marginRate').textContent = Math.round(margin) + '%';
    document.getElementById('rateHint').textContent = '1 CNY ≈ ' + sym + rate;
    document.getElementById('profitMoq').textContent = moq;

    if (cur === 'CNY') {
      document.getElementById('perProfit').textContent = '¥' + perProfitCny.toFixed(2);
      document.getElementById('batchProfit').textContent = '¥' + batchProfitCny.toFixed(2);
      document.getElementById('profitCny').style.display = 'none';
    } else {
      var per = perProfitCny * rate;
      var batch = batchProfitCny * rate;
      var dec = (cur === 'VND' || cur === 'IDR') ? 0 : 2;
      document.getElementById('perProfit').textContent = sym + per.toFixed(dec);
      document.getElementById('batchProfit').textContent = sym + batch.toFixed(dec);
      document.getElementById('profitCny').textContent = '≈ ¥' + perProfitCny.toFixed(2) + ' · ¥' + batchProfitCny.toFixed(2);
      document.getElementById('profitCny').style.display = '';
    }
  };

  // ===== 树形折叠 =====
  window.toggleNode = function (nodeId) {
    var node = document.getElementById(nodeId);
    if (!node) return;
    var expanded = node.classList.contains('expanded');
    if (expanded) {
      node.classList.remove('expanded');
      node.querySelector('.tree-chevron').textContent = '▶';
    } else {
      node.classList.add('expanded');
      node.querySelector('.tree-chevron').textContent = '▼';
    }
  };

  function initTreeState(d) {
    // ③⚠️：有风险 → 展开，无风险 → 折叠
    var cautions = d.cautions || [];
    if (cautions.length === 0) {
      var riskNode = document.getElementById('node-risk');
      if (riskNode) {
        riskNode.classList.remove('expanded');
        riskNode.querySelector('.tree-chevron').textContent = '▶';
      }
    }
    // ③💰：默认折叠
    var profitNode = document.getElementById('node-profit');
    if (profitNode) {
      profitNode.classList.remove('expanded');
      profitNode.querySelector('.tree-chevron').textContent = '▶';
    }
  }

  // ===== 保存按钮 =====
  var currentOfferId = null;

  function showSaveBar(offerId) {
    currentOfferId = offerId;
    var bar = document.getElementById('saveBar');
    if (!bar) {
      // 动态创建 save bar 插入到 ② card 底部
      var summaryCard = document.getElementById('sec-summary');
      if (!summaryCard) return;
      bar = document.createElement('div');
      bar.id = 'saveBar';
      bar.className = 'save-bar';
      bar.style.cssText = 'display:flex;margin-top:var(--s3);';
      summaryCard.appendChild(bar);
    }

    var user = checkAuth();
    if (!user) {
      bar.style.display = 'flex';
      bar.innerHTML = '<button class="save-btn" id="saveBtn" onclick="window._inspectLogin()">' +
        t('report.saveBtn', '💾 Save') + '</button>';
      return;
    }

    var savedKey = 'saved_' + offerId;
    if (sessionStorage.getItem(savedKey)) {
      bar.style.display = 'flex';
      bar.innerHTML = '<button class="save-btn saved" disabled>' + t('report.savedBtn', '✓ Saved') + '</button>';
      return;
    }

    bar.style.display = 'flex';
    bar.innerHTML = '<button class="save-btn" id="saveBtn" onclick="window._inspectSave()">' +
      t('report.saveBtn', '💾 Save') + '</button>';
  }

  window._inspectLogin = function () {
    window.location.href = '/api/auth/google/login?redirect=' +
      encodeURIComponent('/inspect.html?offerId=' + encodeURIComponent(currentOfferId || ''));
  };

  window._inspectSave = function () {
    if (!currentOfferId) return;
    var btn = document.getElementById('saveBtn');
    if (btn) { btn.disabled = true; btn.textContent = t('report.savingBtn', 'Saving...'); }

    API.saveReport(currentOfferId)
      .then(function (data) {
        if (data.code === 200) {
          sessionStorage.setItem('saved_' + currentOfferId, '1');
          if (btn) { btn.textContent = t('report.savedBtn', '✓ Saved'); btn.classList.add('saved'); }
          Messages.success('SAVE_OK', 'Saved!');
        } else {
          if (btn) { btn.disabled = false; btn.textContent = t('report.saveBtn', '💾 Save'); }
        }
      })
      .catch(function () {
        if (btn) { btn.disabled = false; btn.textContent = t('report.saveBtn', '💾 Save'); }
      });
  };

  // ===== 骨架屏 / 错误态 =====
  function hideSkeleton() {
    var skel = document.getElementById('skeleton');
    if (skel) skel.style.display = 'none';
  }

  function showError(title, msg) {
    var errEl = document.getElementById('inspectError');
    if (errEl) errEl.style.display = '';
    var titleEl = document.getElementById('errorTitle');
    if (titleEl) titleEl.textContent = title;
    var msgEl = document.getElementById('errorMsg');
    if (msgEl) msgEl.textContent = msg;
  }

  // ===== 页面启动 =====
  var params = new URLSearchParams(window.location.search);
  var lastTaskId = sessionStorage.getItem('lastTaskId');

  if (lastTaskId) {
    startPolling(lastTaskId);
  } else if (params.get('url') || params.get('sample') || params.get('offerId')) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  }
  // 无参数：保持骨架屏，等 redirect 带参过来
})();

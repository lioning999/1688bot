// ===== 判词引擎（前端） =====
// ⚠️ 同步铁律：本文件的判断条件 + 关键数据必须与
//    src/api/domain/verdict_engine.py 的 judge_product() / judge_factory() 完全一致。
//    改任何一处，必须同步改另一处。
//    验证方式：grep 两端 hasCert / isAdvancedCert / isFactory / isTrader 判断条件是否一致。
var Verdict = (function () {
  'use strict';

  var DOMESTIC_FREIGHT = 10;  // ¥，与 report.js 同名常量保持一致

  function formatNum(n) {
    if (n >= 1000) return (n / 1000).toFixed(1).replace('.0', '') + 'k';
    return String(n);
  }

  function isAdvancedCert(data) {
    return data.sellerType === 'super_factory' || data.sellerType === 'flagship'
      || (data.factoryFlags && (data.factoryFlags.indexOf('超级工厂') !== -1
        || data.factoryFlags.indexOf('源头旗舰') !== -1
        || data.factoryFlags.indexOf('实力工厂') !== -1));
  }

  function hasCert(data) {
    return data.certType && data.certType !== 'null';
  }

  function isFactory(data) {
    return data.factoryFlags && data.factoryFlags.indexOf('非生产厂家') === -1
      && (data.factoryFlags.indexOf('生产厂家') !== -1
        || data.sellerType === 'normal_factory' || data.sellerType === 'super_factory');
  }

  function isTrader(data) {
    return data.factoryFlags && data.factoryFlags.indexOf('非生产厂家') !== -1;
  }

  function buildProductVerdict(data) {
    var low = data.priceCNY ? data.priceCNY.low : 0;
    var moq = data.moq || 2;
    var sold = data.sold || 0;
    var deposit = String(Math.floor(low * moq + DOMESTIC_FREIGHT));  // Bug #15：与后端 int() 截断一致
    var unit = data.unit || '件';

    if (hasCert(data) && sold >= 1000 && data.return7day === 'OK') {
      return '✅ 推荐拿样 — 进价 ¥' + low + '、' + moq + unit + '起批、月销 ' + formatNum(sold) + '+' + '，试错成本极低';
    }
    if (hasCert(data) && sold >= 100) {
      return '✅ 可考虑 — 进价 ¥' + low + '、' + moq + unit + '起批、有认证，建议拿样确认';
    }
    if (!hasCert(data) && sold >= 500) {
      return '⚠️ 缺认证 — 销量 ' + formatNum(sold) + '+ 但无验厂认证，¥' + deposit + ' 拿样就能确认品质';
    }
    return '⚠️ 信息不足 — 缺销量和认证数据，¥' + deposit + ' 拿 2 件确认最稳妥';
  }

  function buildFactoryVerdict(data) {
    var years = data.shop_years || 0;
    var certName = data.certType ? data.certType.toUpperCase() : '';

    if (isAdvancedCert(data) && years >= 3) {
      return '✅ 工厂可靠 — ' + years + '年老店+' + certName + '验厂，合作风险低';
    }
    if (isFactory(data) && hasCert(data)) {
      return '✅ 可合作 — ' + years + '年工厂+认证，建议拿样确认产能';
    }
    if (isFactory(data) && !hasCert(data)) {
      return '⚠️ 自称工厂未认证 — 无第三方验厂，先拿样验证，别信嘴上说的';
    }
    if (isTrader(data)) {
      return '⚠️ 非工厂 — 贸易商从第三方拿货，价差可能大，先拿样比对';
    }
    return '⚠️ 数据不足 — 缺少经营信息，建议 WhatsApp 沟通后再决定';
  }

  return {
    isAdvancedCert: isAdvancedCert,
    hasCert: hasCert,
    isFactory: isFactory,
    isTrader: isTrader,
    buildProductVerdict: buildProductVerdict,
    buildFactoryVerdict: buildFactoryVerdict,
    formatNum: formatNum
  };
})();

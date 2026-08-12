// ============================================================
// Sourcely — i18n loader + currency formatter
// 4 locales: zh (HTML default), en, vi, th
// Translations fetched from /lang/i18n/{lang}.json
// All prices stored in USD. Display formatted per locale.
// ============================================================
var I18N = (function() {
  'use strict';

  // ----- Static exchange rates (1 USD = X local units) -----
  // Default values. Overwritten by /api/config on init.
  var RATES = {
    VND: 25450,  THB: 35.7,  IDR: 16100,  MYR: 4.65,  PHP: 57.2,
  };

  var SYMBOLS = {
    VND: '₫', THB: '฿', IDR: 'Rp', MYR: 'RM', PHP: '₱',
  };

  // ----- Locale config -----
  var LOCALES = {
    en: { label: 'English',            currency: 'USD', flag: 'US' },
    zh: { label: '中文',               currency: 'USD', flag: 'CN' },
    vi: { label: 'Tiếng Việt',         currency: 'VND', flag: 'VN' },
    th: { label: 'ภาษาไทย',            currency: 'THB', flag: 'TH' },
  };
  // id removed — no i18n JSON / glossary column / AI translation path

  // ----- State -----
  var current = null;  // { lang, label, currency, flag }
  var messages = {};   // active locale strings
  var zhSnapped = false;
  var _initialized = false;

  // Snapshot Chinese text from HTML (run once before first apply)
  function snapshotZh() {
    if (zhSnapped) return;
    var zh = {};
    var els = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < els.length; i++) {
      var key = els[i].getAttribute('data-i18n');
      if (key) zh[key] = els[i].innerHTML;
    }
    var phs = document.querySelectorAll('[data-i18n-placeholder]');
    for (var j = 0; j < phs.length; j++) {
      var pk = phs[j].getAttribute('data-i18n-placeholder');
      if (pk) zh[pk] = phs[j].placeholder;
    }
    // Cache zh as fallback for keys missing in translations
    messages = zh;
    zhSnapped = true;
  }

  // ----- Detect browser locale -----
  function detect() {
    // Manual selection overrides auto-detection
    if (localStorage.getItem('sourcely_lang_manual') === '1') {
      var saved = localStorage.getItem('sourcely_lang');
      if (saved) return saved;
    }
    // Use shared LANG module if available
    if (typeof LANG !== 'undefined' && LANG.detect) return LANG.detect();
    // Fallback built-in detection
    var lang = (navigator.language || 'en').slice(0, 2).toLowerCase();
    var supported = ['zh', 'en', 'vi', 'th'];
    return supported.indexOf(lang) !== -1 ? lang : 'en';
  }

  // ----- Load locale from JSON file -----
  function load(lang) {
    snapshotZh(); // ensure zh snapshot exists as fallback
    current = LOCALES[lang];
    current.lang = lang;
    if (lang === 'zh') {
      // zh is already in DOM + snapshot, nothing to fetch
      return Promise.resolve();
    }
    return fetch('/lang/i18n/' + lang + '.json')
      .then(function (r) { return r.json(); })
      .then(function (dict) {
        messages = dict;
      })
      .catch(function () {
        // Fallback: try English first, zh snapshot as last resort
        if (lang === 'en') { snapshotZh(); return; }
        return fetch('/lang/i18n/en.json')
          .then(function (r) { return r.json(); })
          .then(function (dict) { messages = dict; })
          .catch(function () { snapshotZh(); });
      });
  }

  // ----- Apply translations to DOM -----
  function apply() {
    var els = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < els.length; i++) {
      var key = els[i].getAttribute('data-i18n');
      if (messages[key]) els[i].innerHTML = messages[key];
    }
    var phs = document.querySelectorAll('[data-i18n-placeholder]');
    for (var j = 0; j < phs.length; j++) {
      var pk = phs[j].getAttribute('data-i18n-placeholder');
      if (messages[pk]) phs[j].placeholder = messages[pk];
    }
    formatAllPrices();
    document.documentElement.lang = current.lang;

    // Sync lang switcher
    var sw = document.getElementById('langSwitcher');
    if (sw) sw.value = current.lang;
  }

  // ----- Bootstrap: detect → load → fetch rates → apply -----
  function init(optLang) {
    if (_initialized) return Promise.resolve();
    _initialized = true;
    var lang = optLang || detect();
    return load(lang)
      .then(fetchRates)
      .then(apply);
  }

  // ----- Manual switch -----
  function switchTo(lang) {
    localStorage.setItem('sourcely_lang', lang);
    localStorage.setItem('sourcely_lang_manual', '1');
    location.reload();
  }

  // ----- Fetch rates from backend /api/config (overwrites defaults) -----
  function fetchRates() {
    if (typeof API === 'undefined' || !API.getConfig) return Promise.resolve();
    return API.getConfig().then(function (res) {
      if (res && res.data && res.data.fxRates) {
        var fx = res.data.fxRates;
        Object.keys(fx).forEach(function (k) {
          if (RATES.hasOwnProperty(k)) RATES[k] = fx[k];
        });
      }
    }).catch(function () {
      // Silently fall back to default RATES
    });
  }

  // ----- Currency formatting -----
  function formatPrice(usd) {
    if (!current || current.currency === 'USD') {
      return '$' + usd.toFixed(2);
    }
    var local = usd * RATES[current.currency];
    var symbol = SYMBOLS[current.currency] || '';

    if (current.currency === 'VND' || current.currency === 'IDR') {
      var rounded = Math.round(local / 1000) * 1000;
      return symbol + rounded.toLocaleString('en-US');
    }
    return symbol + local.toFixed(0);
  }

  function formatPriceRange(usdLow, usdHigh) {
    if (!current || current.currency === 'USD') {
      return '$' + usdLow.toFixed(2) + ' – $' + usdHigh.toFixed(2);
    }
    return formatPrice(usdLow) + ' – ' + formatPrice(usdHigh);
  }

  // Apply to all [data-price-usd] elements
  function formatAllPrices() {
    var els = document.querySelectorAll('[data-price-usd]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var usd = parseFloat(el.getAttribute('data-price-usd'));
      if (isNaN(usd)) continue;
      var rangeHigh = el.getAttribute('data-price-high');
      if (rangeHigh) {
        el.textContent = formatPriceRange(usd, parseFloat(rangeHigh));
      } else {
        el.textContent = formatPrice(usd);
      }
      el.setAttribute('data-last-usd', usd);
    }
  }

  // ----- Public -----
  function getCurrency() { return current && current.currency; }
  function getLocale()   { return current && current.lang; }
  function t(key)        { return messages[key] || ''; }
  function getLocales()  { return LOCALES; }

  return {
    init: init, detect: detect, load: load, apply: apply, switchTo: switchTo,
    formatPrice: formatPrice, formatPriceRange: formatPriceRange,
    formatAllPrices: formatAllPrices,
    getCurrency: getCurrency, getLocale: getLocale, getLocales: getLocales,
    t: t, RATES: RATES, SYMBOLS: SYMBOLS,
  };
})();

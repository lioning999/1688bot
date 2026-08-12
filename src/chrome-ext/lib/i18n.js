// ===== Sourcely — i18n 多语言 =====
// 中文 = HTML 默认文本，非中文从 lang/{lang}.json 加载。

var I18N = (function () {
  'use strict';

  var LOCALES = {
    zh: { label: '中文' },
    en: { label: 'English' },
    vi: { label: 'Tiếng Việt' },
    th: { label: 'ภาษาไทย' }
  };

  var current = LOCALES.zh;
  var messages = {};
  var _initialized = false;

  function detect() {
    var navLang = (navigator.language || 'en').slice(0, 2).toLowerCase();
    var supported = ['zh', 'en', 'vi', 'th'];
    var detected = supported.indexOf(navLang) !== -1 ? navLang : 'en';

    chrome.storage.local.get('sourcely_lang', function (items) {
      load(items.sourcely_lang || detected);
    });
  }

  function load(lang) {
    if (!LOCALES[lang]) lang = 'zh';
    current = LOCALES[lang];
    current.lang = lang;

    if (lang === 'zh') {
      _initialized = true;
      apply();
      return;
    }

    fetch('/lang/' + lang + '.json')
      .then(function (r) { return r.json(); })
      .then(function (dict) {
        messages = dict;
        _initialized = true;
        apply();
      })
      .catch(function () {
        _initialized = true;
      });
  }

  function apply() {
    if (!_initialized) return;

    var els = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < els.length; i++) {
      var key = els[i].getAttribute('data-i18n');
      if (messages[key]) els[i].textContent = messages[key];
    }

    var phs = document.querySelectorAll('[data-i18n-placeholder]');
    for (var j = 0; j < phs.length; j++) {
      var pk = phs[j].getAttribute('data-i18n-placeholder');
      if (messages[pk]) phs[j].placeholder = messages[pk];
    }

    document.documentElement.lang = current.lang;
  }

  function switchTo(lang) {
    if (!LOCALES[lang]) return;
    sessionStorage.setItem('sourcely_lang', lang);
    chrome.storage.local.set({ sourcely_lang: lang });
    load(lang);
  }

  function t(key) {
    return messages[key] || '';
  }

  function getLang() { return current.lang; }

  return {
    detect: detect,
    load: load,
    apply: apply,
    switchTo: switchTo,
    t: t,
    getLang: getLang,
    LOCALES: LOCALES
  };
})();

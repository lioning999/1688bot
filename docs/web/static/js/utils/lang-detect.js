// ===== lang-detect.js — 浏览器语言检测 + 静态页跳转 =====
// 所有页面引用：静态页做跳转，功能页传值给 i18n.js
var LANG = (function () {
  'use strict';

  var SUPPORTED = ['zh', 'en', 'vi', 'th'];
  var DEFAULT = 'en';

  function detect() {
    // localStorage 手动选择优先
    var saved = localStorage.getItem('sourcely_lang');
    if (saved && SUPPORTED.includes(saved)) return saved;
    // 浏览器语言
    var browser = (navigator.language || DEFAULT).slice(0, 2).toLowerCase();
    return SUPPORTED.includes(browser) ? browser : DEFAULT;
  }

  // 静态页跳转：当前页面不在正确的语言子目录时，跳转到对应语言版本
  function redirectStatic(pageName) {
    var lang = detect();
    var path = location.pathname;
    // 已经在正确语言路径则不动
    if (path.startsWith('/' + lang + '/')) return;
    // 否则跳转
    location.replace('/' + lang + '/' + pageName);
  }

  return { detect: detect, redirectStatic: redirectStatic, SUPPORTED: SUPPORTED };
})();

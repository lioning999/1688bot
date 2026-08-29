// ===== Sourcely — 统一 toast 提示 =====
// 唯一 toast 出口。所有提示条统一走 Toast.show(msg, type)。

var Toast = (function () {
  'use strict';

  var _timer = null;

  function show(msg, type) {
    var el = document.createElement('div');
    el.className = 'toast ' + (type || 'info');
    el.textContent = msg;
    document.body.appendChild(el);
    if (_timer) clearTimeout(_timer);   // 新 toast 顶掉旧 toast，不重叠
    _timer = setTimeout(function () { el.remove(); _timer = null; }, 3000);
  }

  window.addEventListener('pagehide', function () {   // 关页清理未到期的 timer
    if (_timer) { clearTimeout(_timer); _timer = null; }
  });

  return { show: show };
})();

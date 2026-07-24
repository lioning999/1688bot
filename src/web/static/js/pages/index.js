// ===== 首页逻辑 =====
(function () {
  'use strict';

  var searchInput = document.getElementById('searchInput');
  var searchBtn = document.getElementById('searchBtn');

  function doSearch(input) {
    if (!input) return;
    // 提取 offerId
    var m = input.match(/offer(?:Id)?[=/](\d+)/i);
    if (m) {
      window.location.href = 'report.html?offerId=' + m[1];
      return;
    }
    // 完整 1688 URL
    if (input.indexOf('detail.1688.com') !== -1) {
      window.location.href = 'report.html?url=' + encodeURIComponent(input);
      return;
    }
    if (typeof Toast !== 'undefined') {
      Toast.warning('请粘贴有效的 1688 商品链接<br><small style="color:var(--ink-3)">示例：https://detail.1688.com/offer/xxxxx.html</small>');
    }
  }

  if (searchBtn) {
    searchBtn.disabled = true;
    searchBtn.addEventListener('click', function () {
      doSearch((searchInput && searchInput.value || '').trim());
    });
  }

  if (searchInput) {
    searchInput.addEventListener('input', function () {
      if (searchBtn) searchBtn.disabled = !searchInput.value.trim();
    });
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        doSearch(searchInput.value.trim());
      }
    });
  }
})();

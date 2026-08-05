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
      window.location.href = 'inspect.html?offerId=' + m[1];
      return;
    }
    // 完整 1688 URL
    if (input.indexOf('detail.1688.com') !== -1) {
      window.location.href = 'inspect.html?url=' + encodeURIComponent(input);
      return;
    }
    Messages.warning('INVALID_URL', '请粘贴有效的 1688 商品链接<br><small style="color:var(--ink-3)">示例：https://detail.1688.com/offer/xxxxx.html</small>');
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
  // ===== 评价轮播：每次 1 张卡片，停留 2s，滑入滑出 =====
  var list = document.getElementById('reviewList');
  if (list) {
    var track = document.getElementById('reviewTrack');
    var cards = track.querySelectorAll('.review-card');
    var total = cards.length;
    var step = 412;                // 400px 卡片 + 12px gap
    var stay = 2000;              // 停留 ms
    var transition = 500;         // 滑动 ms
    var current = 0;
    var paused = false;
    var _timer = null;
    var _resetting = false;

    // 克隆一组 → 循环时无缝衔接
    for (var ci = 0; ci < total; ci++) {
      track.appendChild(cards[ci].cloneNode(true));
    }

    function go(n, animate) {
      track.style.transition = animate ? 'transform 0.5s ease' : 'none';
      track.style.transform = 'translateX(-' + (n * step) + 'px)';
      current = n;
    }

    function next() {
      if (paused || _resetting) return;
      var nxt = current + 1;
      go(nxt, true);
      // 滑到克隆区末尾 → 无动画跳回原始位置
      if (nxt >= total) {
        _resetting = true;
        setTimeout(function () {
          go(nxt - total, false);
          _resetting = false;
        }, transition + 50);
      }
    }

    function cycle() {
      _timer = setTimeout(function () {
        next();
        cycle();
      }, stay + transition);
    }

    list.addEventListener('mouseenter', function () { paused = true; });
    list.addEventListener('mouseleave', function () { paused = false; });

    go(0, false);
    cycle();
  }
})();

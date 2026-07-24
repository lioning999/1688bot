// ===== 历史记录页 =====
// 登录用户查看/删除过往分析记录（只读 DB，不调 Apify）

var historyList = document.getElementById('historyList');
var historyEmpty = document.getElementById('historyEmpty');
var loginPrompt = document.getElementById('loginPrompt');
var pageHint = document.getElementById('pageHint');

// ===== 加载历史 =====
var user = checkAuth();
if (!user) {
  loginPrompt.style.display = 'block';
  pageHint.textContent = '登录后可查看历史分析记录';
} else {
  loadHistory();
}

function loadHistory() {
  API.getHistory()
    .then(function(data) {
      if (data.code === 401) {
        loginPrompt.style.display = 'block';
        pageHint.textContent = '登录已过期，请重新登录';
        return;
      }

      var items = (data.data && data.data.items) || [];
      if (!items.length) {
        historyEmpty.style.display = 'block';
        return;
      }

      historyList.style.display = 'block';
      pageHint.textContent = '共 ' + items.length + ' 条记录';
      renderItems(items);
    })
    .catch(function(err) {
      console.warn('History load failed:', err);
      pageHint.textContent = '加载失败，请刷新页面重试';
    });
}

function renderItems(items) {
  var html = '';
  items.forEach(function(item) {
    var price = '';
    if (item.price_min != null) {
      price = '¥' + item.price_min;
      if (item.price_max && item.price_max !== item.price_min) {
        price += ' – ¥' + item.price_max;
      }
    }

    var timeAgo = formatTimeAgo(item.created_at);
    var imgHtml = item.image_url
      ? '<img class="hi-thumb" src="' + escapeAttr(item.image_url) + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">'
      : '<div class="hi-thumb hi-thumb-empty"></div>';

    html +=
      '<div class="history-item" data-id="' + item.id + '">' +
        '<a href="report.html?offerId=' + escapeAttr(item.offer_id) + '" class="hi-link">' +
          imgHtml +
          '<div class="hi-body">' +
            '<div class="hi-title">' + escapeHTML(item.title || '(无标题)') + '</div>' +
            '<div class="hi-meta">' +
              '<span class="hi-price">' + (price || '—') + '</span>' +
              '<span class="hi-time">' + timeAgo + '</span>' +
            '</div>' +
          '</div>' +
        '</a>' +
        '<button class="hi-del" data-id="' + item.id + '" title="删除">×</button>' +
      '</div>';
  });
  historyList.innerHTML = html;

  // 绑定删除事件
  var delBtns = historyList.querySelectorAll('.hi-del');
  delBtns.forEach(function(btn) {
    btn.addEventListener('click', onDelete);
  });
}

// ===== 删除 =====

function onDelete(e) {
  e.preventDefault();
  e.stopPropagation();

  var btn = e.currentTarget;
  var id = parseInt(btn.getAttribute('data-id'), 10);
  if (!id) return;

  if (!confirm('确定删除这条记录吗？')) return;

  btn.disabled = true;
  btn.textContent = '…';

  API.deleteHistory(id)
    .then(function(data) {
      if (data.code === 200) {
        // 从 DOM 移除
        var item = btn.closest('.history-item');
        if (item) item.remove();

        // 更新计数
        var remaining = historyList.querySelectorAll('.history-item').length;
        if (remaining === 0) {
          historyList.style.display = 'none';
          historyEmpty.style.display = 'block';
          pageHint.textContent = '暂无分析记录';
        } else {
          pageHint.textContent = '共 ' + remaining + ' 条记录';
        }
      } else {
        btn.disabled = false;
        btn.textContent = '×';
        if (typeof Toast !== 'undefined') {
          Toast.error('删除失败，请稍后重试');
        }
      }
    })
    .catch(function() {
      btn.disabled = false;
      btn.textContent = '×';
      if (typeof Toast !== 'undefined') {
        Toast.error('网络错误，请稍后重试');
      }
    });
}

// ===== 工具函数 =====

function formatTimeAgo(dateStr) {
  if (!dateStr) return '';
  var now = Date.now();
  var then = new Date(dateStr.replace(' ', 'T') + (dateStr.indexOf('+') === -1 ? 'Z' : '')).getTime();
  if (isNaN(then)) return dateStr;
  var diff = Math.floor((now - then) / 1000);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  if (diff < 604800) return Math.floor(diff / 86400) + ' 天前';
  return dateStr.slice(0, 10);
}

function escapeHTML(str) {
  var div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

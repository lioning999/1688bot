// ===== 分享功能 =====
// 依赖：html2canvas（CDN 加载）、DOM 元素 #shareOverlay / #shareCardTmpl / #mainImg / .prod-title / .prod-price / .badge-row / .trust-bar
var Share = (function () {
  'use strict';

  function escapeHTML(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function buildShareCard() {
    var mainImg = document.getElementById('mainImg');
    var mainImgSrc = mainImg ? mainImg.src : '';
    // 通过后端代理绕过 1688 CDN 不返回 CORS 头的问题
    var proxySrc = mainImgSrc ? '/api/proxy/image?url=' + encodeURIComponent(mainImgSrc) : '';
    var titleEl = document.querySelector('.prod-title');
    var title = titleEl ? titleEl.textContent.trim() : '';
    var priceEl = document.querySelector('.prod-price');
    var priceText = priceEl ? priceEl.textContent.trim() : '';
    var badgeEl = document.querySelector('.badge-row');
    var badges = badgeEl ? badgeEl.innerHTML : '';
    var trustEl = document.querySelector('.trust-bar');
    var trustHTML = trustEl ? trustEl.innerHTML : '';
    var shareCardTmpl = document.getElementById('shareCardTmpl');

    var html = '<div style="padding:32px 28px 0;background:#FFFFFF;">';

    html += '<div style="margin-bottom:24px;">';
    html += '<div style="font-family:\'Noto Serif SC\',\'Songti SC\',serif;font-weight:700;font-size:22px;color:#232A38;letter-spacing:1px;">源采 SOURCELY</div>';
    html += '</div>';

    html += '<div style="width:694px;height:694px;border-radius:12px;overflow:hidden;background:#FAFAFA;margin-bottom:24px;">';
    html += '<img src="' + proxySrc + '" style="width:100%;height:100%;object-fit:cover;display:block;">';
    html += '</div>';

    html += '<div style="font-family:\'Noto Serif SC\',\'Songti SC\',serif;font-weight:700;font-size:22px;color:#232A38;line-height:1.4;margin-bottom:12px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">' + escapeHTML(title) + '</div>';

    html += '<div style="font-family:\'JetBrains Mono\',\'SF Mono\',Menlo,monospace;font-size:30px;font-weight:700;color:#D6432F;margin-bottom:24px;">' + priceText + '</div>';

    html += '<div style="margin-bottom:16px;">' + badges + '</div>';

    html += '<div style="padding:10px 18px;background:#F8F7F3;border-left:4px solid #2F8A5B;border-radius:0 6px 6px 0;font-size:16px;font-weight:600;color:#232A38;display:flex;flex-wrap:wrap;gap:8px 20px;margin-bottom:24px;">' + trustHTML + '</div>';

    html += '<div style="background:#1E3A5F;margin:0 -28px;padding:16px 28px;display:flex;align-items:center;justify-content:space-between;">';
    html += '<div>';
    html += '<div style="font-weight:700;font-size:17px;color:#FFFFFF;letter-spacing:2px;">🔍 SOURCELY</div>';
    html += '<div style="font-size:13px;color:rgba(255,255,255,.75);margin-top:4px;">扫码查看完整分析 →</div>';
    html += '</div>';
    html += '<div style="font-size:14px;color:rgba(255,255,255,.6);font-family:\'JetBrains Mono\',\'SF Mono\',monospace;">sourcely.com</div>';
    html += '</div>';

    html += '</div>';

    if (shareCardTmpl) {
      shareCardTmpl.innerHTML = html;
      return shareCardTmpl.firstElementChild;
    }
    return null;
  }

  var shareBlob = null;
  var shareFile = null;

  function renderAndShow() {
    if (typeof html2canvas === 'undefined') {
      console.warn('html2canvas not loaded, share disabled');
      return;
    }
    var card = buildShareCard();
    if (!card) return;
    card.offsetHeight;

    html2canvas(card, {
      scale: 2,
      backgroundColor: '#FFFFFF'
    }).then(function (canvas) {
      canvas.toBlob(function (blob) {
        shareBlob = blob;
        shareFile = new File([blob], 'sourcely-decision-card.png', { type: 'image/png' });
        var sharePreviewImg = document.getElementById('sharePreviewImg');
        var shareOverlay = document.getElementById('shareOverlay');
        if (sharePreviewImg) {
          if (sharePreviewImg._blobUrl) URL.revokeObjectURL(sharePreviewImg._blobUrl);
          sharePreviewImg._blobUrl = URL.createObjectURL(blob);
          sharePreviewImg.src = sharePreviewImg._blobUrl;
        }
        if (shareOverlay) shareOverlay.classList.add('show');
      }, 'image/png', 0.85);
    }).catch(function (err) {
      console.warn('html2canvas render error:', err);
      if (typeof Toast !== 'undefined') {
        Toast.error('图片生成失败，请重试。如持续失败请截图分享。', true);
      }
    });
  }

  function closeSheet() {
    var shareOverlay = document.getElementById('shareOverlay');
    var shareCardTmpl = document.getElementById('shareCardTmpl');
    var sharePreviewImg = document.getElementById('sharePreviewImg');
    if (shareOverlay) shareOverlay.classList.remove('show');
    if (shareCardTmpl) shareCardTmpl.innerHTML = '';
    // Bug #16：清理 blob URL
    if (sharePreviewImg && sharePreviewImg._blobUrl) {
      URL.revokeObjectURL(sharePreviewImg._blobUrl);
      sharePreviewImg._blobUrl = null;
    }
  }

  function saveImage() {
    if (!shareBlob) return;
    var a = document.createElement('a');
    var downloadUrl = URL.createObjectURL(shareBlob);
    a.href = downloadUrl;
    a.download = 'sourcely-decision-card.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // Bug #16：延迟回收 blob URL
    setTimeout(function () { URL.revokeObjectURL(downloadUrl); }, 100);
  }

  function copyPageLink() {
    var pageUrl = window.location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(pageUrl).then(function () {
        if (typeof Toast !== 'undefined') Toast.success('链接已复制！<br><small style="color:var(--ink-3)">可粘贴到微信/WhatsApp/聊天</small>');
      }).catch(function () {
        prompt('复制此链接分享：', pageUrl);
      });
    } else {
      prompt('复制此链接分享：', pageUrl);
    }
  }

  function bindEvents() {
    var shareBtnMain = document.getElementById('shareBtnMain');
    var shareClose = document.getElementById('shareClose');
    var shareSave = document.getElementById('shareSave');
    var shareCopy = document.getElementById('shareCopy');
    var shareOverlay = document.getElementById('shareOverlay');

    if (shareBtnMain) shareBtnMain.addEventListener('click', renderAndShow);
    if (shareClose) shareClose.addEventListener('click', closeSheet);
    if (shareSave) shareSave.addEventListener('click', saveImage);
    if (shareCopy) shareCopy.addEventListener('click', copyPageLink);
    if (shareOverlay) {
      shareOverlay.addEventListener('click', function (e) {
        if (e.target === shareOverlay) closeSheet();
      });
    }
  }

  return {
    bindEvents: bindEvents,
    renderAndShow: renderAndShow,
    closeSheet: closeSheet,
    saveImage: saveImage
  };
})();

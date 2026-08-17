"""S1.6 回归测试 — ext_id 零校验修复（Open Redirect + JWT 泄漏）。

锁定 routes/auth.py 的 _sanitize_ext_id 校验逻辑，防止有人改回来：
  - 合法 32 位 a-p → 原样返回
  - 空 → 空（Web 流，token 走 cookie）
  - 恶意 / 大写 / 过短 → 回落默认 ID
  - google_login 端点构造的 state 不得含恶意 ext_id（否则回调拼出 https://evil.com/?...token=...）
"""

import pytest

import routes.auth as auth
from config import Config

# Chrome 扩展 ID 固定 32 位小写 a-p（base16）
LEGAL_EXT_ID = "abcdefghijklmnopabcdefghijklmnop"


@pytest.mark.parametrize(
    "ext_id, expected",
    [
        ("", ""),                                          # 空 → 空（Web 流）
        (LEGAL_EXT_ID, LEGAL_EXT_ID),                      # 合法 → 原值
        ("evil.com/?", Config.CHROME_EXTENSION_ID),        # 恶意 → 回落默认
        ("EVILCOM", Config.CHROME_EXTENSION_ID),           # 大写 → 回落默认
        ("abcdefghijklmnop", Config.CHROME_EXTENSION_ID),  # 16 位过短 → 回落默认
    ],
)
def test_sanitize_ext_id(ext_id, expected):
    assert auth._sanitize_ext_id(ext_id) == expected


@pytest.mark.asyncio
async def test_google_login_blocks_malicious_ext_id(monkeypatch):
    """恶意 ext_id 不得进入 state（否则回调拼出 https://evil.com/?...token=...）。"""
    captured = {}

    def fake_get_auth_url(state=""):
        captured["state"] = state
        return "https://accounts.google.com/fake"

    monkeypatch.setattr(auth.auth_service, "get_auth_url", fake_get_auth_url)

    await auth.google_login(platform="extension", ext_id="evil.com/?")

    assert "evil.com" not in captured["state"]


@pytest.mark.asyncio
async def test_google_login_keeps_legal_ext_id(monkeypatch):
    """合法 ext_id 原样进入 state。"""
    captured = {}

    def fake_get_auth_url(state=""):
        captured["state"] = state
        return "https://accounts.google.com/fake"

    monkeypatch.setattr(auth.auth_service, "get_auth_url", fake_get_auth_url)

    await auth.google_login(platform="extension", ext_id=LEGAL_EXT_ID)

    assert captured["state"] == f"extension:{LEGAL_EXT_ID}"

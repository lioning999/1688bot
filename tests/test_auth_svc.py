"""auth_svc 配额方法测试 — 锁住 route 层下沉的配额判断行为。

覆盖「查配额 + 懒重置补地板 + tier 地板」4 场景，防止下沉时搬错：
  1 配额充足 + 今天已重置 → 不懒重置，原值返回
  2 last_reset_date 是昨天 → 懒重置补地板
  3 配额 0 + 今天已重置 → 返回 0（POST 层据此抛 QUOTA_EXHAUSTED）
  4 tier free vs paid → 地板 3 vs 20
"""

from datetime import date, timedelta

import pytest

import services.auth_svc as auth_svc
from services.auth_svc import AuthService


def _info(quota: int, tier: str = "free", last_reset=None):
    return {"quota": quota, "tier": tier, "last_reset_date": last_reset}


@pytest.mark.asyncio
async def test_quota_sufficient_same_day_no_reset(monkeypatch):
    """场景1：配额充足 + 今天已重置 → 不调懒重置，原值返回。"""
    today = date.today()
    reset_calls = []

    async def fake_get(user_id):
        return _info(10, last_reset=today)

    async def fake_reset(user_id, tier, floor):
        reset_calls.append(floor)
        return floor

    monkeypatch.setattr(auth_svc._user_repo, "get_quota_info", fake_get)
    monkeypatch.setattr(auth_svc._user_repo, "lazy_reset_daily_quota", fake_reset)

    r = await AuthService().get_quota_with_reset(1)

    assert r["remaining"] == 10
    assert reset_calls == []


@pytest.mark.asyncio
async def test_quota_yesterday_resets_to_floor(monkeypatch):
    """场景2：last_reset_date 是昨天 → 懒重置补地板。"""
    yesterday = date.today() - timedelta(days=1)

    async def fake_get(user_id):
        return _info(0, last_reset=yesterday)

    async def fake_reset(user_id, tier, floor):
        return floor

    monkeypatch.setattr(auth_svc._user_repo, "get_quota_info", fake_get)
    monkeypatch.setattr(auth_svc._user_repo, "lazy_reset_daily_quota", fake_reset)

    r = await AuthService().get_quota_with_reset(1)

    assert r["remaining"] == r["daily_limit"]  # 补地板后 remaining == 当日地板


@pytest.mark.asyncio
async def test_quota_zero_same_day_returns_zero(monkeypatch):
    """场景3：配额 0 + 今天已重置 → 返回 0（不抛异常，POST 层据此判断）。"""
    today = date.today()

    async def fake_get(user_id):
        return _info(0, last_reset=today)

    async def fake_reset(user_id, tier, floor):
        raise AssertionError("今天已重置，不应调懒重置")

    monkeypatch.setattr(auth_svc._user_repo, "get_quota_info", fake_get)
    monkeypatch.setattr(auth_svc._user_repo, "lazy_reset_daily_quota", fake_reset)

    r = await AuthService().get_quota_with_reset(1)

    assert r["remaining"] == 0


@pytest.mark.asyncio
async def test_quota_tier_floor_free_vs_paid(monkeypatch):
    """场景4：tier free → 地板 3，paid → 地板 20。"""
    yesterday = date.today() - timedelta(days=1)
    state = {"tier": "free"}

    async def fake_get(user_id):
        return _info(0, tier=state["tier"], last_reset=yesterday)

    async def fake_reset(user_id, tier, floor):
        return floor

    monkeypatch.setattr(auth_svc._user_repo, "get_quota_info", fake_get)
    monkeypatch.setattr(auth_svc._user_repo, "lazy_reset_daily_quota", fake_reset)

    assert (await AuthService().get_quota_with_reset(1))["remaining"] == 3
    state["tier"] = "paid"
    assert (await AuthService().get_quota_with_reset(1))["remaining"] == 20

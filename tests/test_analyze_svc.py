"""analyze_svc 编排层测试 — 测行为不测实现，外部依赖全 mock。

覆盖完善修复方案 T1-T6：
  T1 正常分析落库 raw_json + display_i18n
  T2 Apify 失败退配额 + 记失败
  T3 DB 命中同语言跳 Apify 退配额
  T4 DB 命中缺语言重建 + 追加语言
  T5 并发同 offer_id 只扣一次配额（验 G1）
  T6 mapper 抛异常退配额（验 G4）
"""

import asyncio
import contextlib
import json
import time

import pytest

import services.analyze_svc as analyze_svc
from services.analyze_svc import AnalyzeService
from utils.exceptions import ExternalServiceError


class FakeRepo:
    """内存版 AnalysisRepository — 捕获调用，不碰真实 DB。"""

    def __init__(self, get_by_offer_id_result=None):
        self._get_by_offer_id_result = get_by_offer_id_result
        self.upsert_calls = 0
        self.last_upsert = None
        self.update_calls = 0

    async def get_by_offer_id(self, offer_id: str, user_id: int):
        return self._get_by_offer_id_result

    async def upsert(self, data: dict):
        self.upsert_calls += 1
        self.last_upsert = data
        return 1

    async def update_display_i18n(self, offer_id: str, user_id: int, display_i18n_json: str):
        self.update_calls += 1
        return True

    async def cleanup_excess(self, user_id: int, max_count: int):
        return 0


def _seed_task(task_id: str) -> None:
    """预置 _tasks 条目（_run 会写 running 状态）。"""
    analyze_svc._tasks[task_id] = {"status": "pending", "result": None, "created_at": time.time()}


# ---- T1 正常分析落库 ----
@pytest.mark.asyncio
async def test_t1_normal_analysis_saves_raw_and_display(monkeypatch):
    repo = FakeRepo()
    svc = AnalyzeService(repo=repo)

    async def fake_fetch(url: str):
        return {"offerId": "offer1", "title": "原始标题", "price": {"min": 1.0, "max": 2.0}}

    async def fake_increment(user_id: int):
        return None

    async def fake_get_quota_info(user_id: int):
        return {"tier": "free"}

    async def fake_build(mapped, offer_id, lang):
        return {"display": {"title": "最终标题"}}

    monkeypatch.setattr(analyze_svc.apify_adapter, "fetch_product_by_url", fake_fetch)
    monkeypatch.setattr(analyze_svc._user_repo, "increment_quota", fake_increment)
    monkeypatch.setattr(analyze_svc._user_repo, "get_quota_info", fake_get_quota_info)
    monkeypatch.setattr(analyze_svc, "map_raw", lambda raw, url, oid: {"title": "映射标题", "image": "http://x.jpg"})
    monkeypatch.setattr(analyze_svc, "build_result_with_display", fake_build)

    task_id = "t1"
    _seed_task(task_id)

    result = await svc._run(task_id, "offer1", "http://x", lang="zh", user_id=1)

    assert result["display"]["title"] == "最终标题"
    assert repo.upsert_calls == 1
    assert repo.last_upsert["raw_json"]
    assert repo.last_upsert["display_i18n"]
    assert json.loads(repo.last_upsert["display_i18n"])["zh"]["title"] == "最终标题"


# ---- T2 Apify 失败退配额 ----
@pytest.mark.asyncio
async def test_t2_apify_fail_refunds_quota(monkeypatch):
    repo = FakeRepo()
    svc = AnalyzeService(repo=repo)

    refunded = []

    async def fake_increment(user_id: int):
        refunded.append(user_id)

    async def fake_fetch(url: str):
        raise ExternalServiceError(service_name="Apify", details={"reason": "fetch_failed"})

    monkeypatch.setattr(analyze_svc._user_repo, "increment_quota", fake_increment)
    monkeypatch.setattr(analyze_svc.apify_adapter, "fetch_product_by_url", fake_fetch)

    task_id = "t2"
    _seed_task(task_id)

    with pytest.raises(ExternalServiceError):
        await svc._run(task_id, "offer2", "http://x", lang="zh", user_id=1)

    assert len(refunded) == 1
    assert analyze_svc._fail_count["offer2"][0] == 1


# ---- T3 DB 命中同语言跳 Apify ----
@pytest.mark.asyncio
async def test_t3_db_hit_same_lang_skips_apify(monkeypatch):
    repo = FakeRepo(get_by_offer_id_result={
        "raw": {"title": "缓存原始"},
        "display_i18n": json.dumps({"zh": {"title": "缓存标题"}}),
    })
    svc = AnalyzeService(repo=repo)

    refunded = []
    apify_calls = []

    async def fake_increment(user_id: int):
        refunded.append(user_id)

    async def fake_fetch(url: str):
        apify_calls.append(url)
        return {"title": "不该调用"}

    monkeypatch.setattr(analyze_svc._user_repo, "increment_quota", fake_increment)
    monkeypatch.setattr(analyze_svc.apify_adapter, "fetch_product_by_url", fake_fetch)

    task_id = "t3"
    _seed_task(task_id)

    result = await svc._run(task_id, "offer3", "http://x", lang="zh", user_id=1)

    assert apify_calls == []
    assert len(refunded) == 1
    assert result["display"]["title"] == "缓存标题"


# ---- T4 DB 命中缺语言重建 ----
@pytest.mark.asyncio
async def test_t4_db_hit_missing_lang_rebuilds(monkeypatch):
    repo = FakeRepo(get_by_offer_id_result={
        "raw": {"title": "缓存原始"},
        "display_i18n": json.dumps({"zh": {"title": "中文标题"}}),
    })
    svc = AnalyzeService(repo=repo)

    refunded = []
    apify_calls = []

    async def fake_increment(user_id: int):
        refunded.append(user_id)

    async def fake_fetch(url: str):
        apify_calls.append(url)
        return {"title": "不该调用"}

    async def fake_build(mapped, offer_id, lang):
        return {"display": {"title": "英文标题", "_aiGenerated": "en"}}

    monkeypatch.setattr(analyze_svc._user_repo, "increment_quota", fake_increment)
    monkeypatch.setattr(analyze_svc.apify_adapter, "fetch_product_by_url", fake_fetch)
    monkeypatch.setattr(analyze_svc, "map_raw", lambda raw, url, oid: {"title": "重建标题"})
    monkeypatch.setattr(analyze_svc, "build_result_with_display", fake_build)

    task_id = "t4"
    _seed_task(task_id)

    result = await svc._run(task_id, "offer4", "http://x", lang="en", user_id=1)

    assert apify_calls == []
    assert repo.update_calls == 1
    assert len(refunded) == 1
    assert result["display"]["title"] == "英文标题"


# ---- T5 并发同 offer_id 只扣一次配额（验 G1） ----
@pytest.mark.asyncio
async def test_t5_concurrent_same_offer_id_single_decrement(monkeypatch):
    repo = FakeRepo()
    svc = AnalyzeService(repo=repo)

    decrements = []

    async def slow_decrement(user_id: int):
        decrements.append(user_id)
        await asyncio.sleep(0)  # 让出，暴露 G1 竞态窗口
        return True

    async def fake_increment(user_id: int):
        return None

    async def fake_get_quota_info(user_id: int):
        return {"tier": "free"}

    async def fake_fetch(url: str):
        return {"offerId": "same", "title": "x"}

    async def fake_build(mapped, offer_id, lang):
        return {"display": {"title": "x"}}

    monkeypatch.setattr(analyze_svc._user_repo, "decrement_quota", slow_decrement)
    monkeypatch.setattr(analyze_svc._user_repo, "increment_quota", fake_increment)
    monkeypatch.setattr(analyze_svc._user_repo, "get_quota_info", fake_get_quota_info)
    monkeypatch.setattr(analyze_svc.apify_adapter, "fetch_product_by_url", fake_fetch)
    monkeypatch.setattr(analyze_svc, "map_raw", lambda raw, url, oid: {"title": "x"})
    monkeypatch.setattr(analyze_svc, "build_result_with_display", fake_build)

    await asyncio.gather(
        svc.start("same", user_id=1, raw_url="http://x", lang="zh"),
        svc.start("same", user_id=1, raw_url="http://x", lang="zh"),
    )

    # 等待后台 _run 完成，避免 pending task 警告
    for entry in list(analyze_svc._pending.values()):
        with contextlib.suppress(Exception):
            await entry["task"]

    assert len(decrements) == 1, f"并发同 offer_id 应只扣一次配额，实际 {len(decrements)} 次"


# ---- T6 mapper 抛异常退配额（验 G4） ----
@pytest.mark.asyncio
async def test_t6_mapper_raises_refunds_quota(monkeypatch):
    repo = FakeRepo()
    svc = AnalyzeService(repo=repo)

    refunded = []

    async def fake_increment(user_id: int):
        refunded.append(user_id)

    async def fake_fetch(url: str):
        return {"offerId": "offer6", "title": "原始"}

    def boom(raw, url, oid):
        raise ValueError("map_raw 爆炸")

    monkeypatch.setattr(analyze_svc._user_repo, "increment_quota", fake_increment)
    monkeypatch.setattr(analyze_svc.apify_adapter, "fetch_product_by_url", fake_fetch)
    monkeypatch.setattr(analyze_svc, "map_raw", boom)

    task_id = "t6"
    _seed_task(task_id)

    with pytest.raises(ExternalServiceError):
        await svc._run(task_id, "offer6", "http://x", lang="zh", user_id=1)

    assert len(refunded) == 1, "mapper 抛异常应退配额（G4）"


# ---- G2 合并请求语言不同 → 第二个请求重建正确语言 ----
@pytest.mark.asyncio
async def test_g2_coalesce_diff_lang_rebuilds(monkeypatch):
    repo = FakeRepo()
    svc = AnalyzeService(repo=repo)

    get_calls = {"n": 0}

    async def fake_get(offer_id, user_id):
        get_calls["n"] += 1
        if get_calls["n"] == 1:
            return None  # 第一个请求：未命中，走 Apify
        return {"raw": {"offerId": "X"}, "display_i18n": None}  # 第二个重建：命中 raw

    async def slow_fetch(url):
        await asyncio.sleep(0.05)  # 让第二个请求能合并进来
        return {"offerId": "X", "title": "raw"}

    async def fake_build(mapped, offer_id, lang):
        return {"display": {"title": f"t-{lang}"}}

    async def fake_decrement(user_id):
        return True

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(repo, "get_by_offer_id", fake_get)
    monkeypatch.setattr(analyze_svc.apify_adapter, "fetch_product_by_url", slow_fetch)
    monkeypatch.setattr(analyze_svc, "map_raw", lambda raw, url, oid: {"title": "mapped"})
    monkeypatch.setattr(analyze_svc, "build_result_with_display", fake_build)
    monkeypatch.setattr(analyze_svc._user_repo, "decrement_quota", fake_decrement)
    monkeypatch.setattr(analyze_svc._user_repo, "increment_quota", noop)
    monkeypatch.setattr(analyze_svc._user_repo, "get_quota_info", noop)

    t1 = await svc.start("X", user_id=1, raw_url="http://x", lang="en")
    t2 = await svc.start("X", user_id=1, raw_url="http://x", lang="zh")

    await asyncio.sleep(0.2)  # 等第一个 Apify 完成 + 第二个重建

    r1 = svc.get_task(t1)
    r2 = svc.get_task(t2)
    assert r1 and r1["result"]["display"]["title"] == "t-en", f"第一个请求应为 en，实际 {r1}"
    assert r2 and r2["result"]["display"]["title"] == "t-zh", f"第二个合并请求应为 zh，实际 {r2}"


# ---- G3 容器硬上限（_cleanup_containers FIFO 删最旧 + _pending 并发拒绝） ----


def test_g3_task_cap_fifo_evicts_oldest():
    cap = analyze_svc._MAX_TASKS
    now = time.time()
    for i in range(cap + 5):
        analyze_svc._tasks[f"t{i}"] = {"status": "done", "result": None, "created_at": now - (cap + 5 - i) * 0.001}
    analyze_svc._cleanup_containers()
    assert len(analyze_svc._tasks) == cap
    for i in range(5):
        assert f"t{i}" not in analyze_svc._tasks, f"最旧 t{i} 应被 FIFO 删除"
    assert f"t{cap + 4}" in analyze_svc._tasks, "最新条目应保留"


def test_g3_fail_cap_fifo_evicts_oldest():
    cap = analyze_svc._MAX_FAIL_COUNT
    now = time.time()
    for i in range(cap + 5):
        analyze_svc._fail_count[f"o{i}"] = (1, now - (cap + 5 - i) * 0.001)
    analyze_svc._cleanup_containers()
    assert len(analyze_svc._fail_count) == cap
    for i in range(5):
        assert f"o{i}" not in analyze_svc._fail_count, f"最旧 o{i} 应被 FIFO 删除"


@pytest.mark.asyncio
async def test_g3_pending_cap_rejects_when_full():
    repo = FakeRepo()
    svc = AnalyzeService(repo=repo)
    for i in range(analyze_svc._MAX_PENDING):
        analyze_svc._pending[f"offer{i}"] = {"task": None, "lang": "zh", "raw_url": "http://x"}
    task_id = await svc.start("new_offer", user_id=0, raw_url="http://x", lang="zh")
    t = analyze_svc._tasks.get(task_id)
    assert t and t["status"] == "failed"
    assert t["error_msg_code"] == "GLOBAL_RATE_LIMIT"

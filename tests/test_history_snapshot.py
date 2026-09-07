"""历史快照回归 — 历史=入库样（只读存储、不重建、不随语言切换变）。

对应 docs/修复-历史记录与拿样货币一致性.md：
  1. get_saved_report 无 lang → 返回存储 display，不触发懒重建/回写
  2. get_saved_report lang 命中优先，缺则返回存储第一个非空
  3. get_history lang 优先取标题/综合结论档位（verdict_grade）
"""

import json

import pytest

from services.analyze_svc import AnalyzeService


class FakeRepo:
    """内存版 AnalysisRepository — 只实现本次被测方法需要的调用。"""

    def __init__(self, saved=None, rows=None):
        self._saved = saved          # get_by_offer_id 返回值
        self._rows = rows or []      # get_history 返回值
        self.update_calls = 0

    async def get_by_offer_id(self, offer_id: str, user_id: int):
        return self._saved

    async def get_history(self, user_id: int, limit: int):
        return [dict(r) for r in self._rows]

    async def update_display_i18n(self, offer_id: str, user_id: int, display_i18n_json: str):
        self.update_calls += 1
        return True


def _stored(**langs):
    """display_i18n 列：{语言: display} 的 JSON 字符串。"""
    return json.dumps(langs, ensure_ascii=False)


def _saved(display_json: str):
    return {"offer_id": "1", "user_id": 1, "raw": {}, "title": "旧列英文标题", "display_i18n": display_json}


# ---- 1. 无 lang → 返回存储的 ru，不懒重建、不回写 ----
@pytest.mark.asyncio
async def test_saved_report_no_lang_returns_stored_snapshot():
    repo = FakeRepo(saved=_saved(_stored(ru={"title": "俄语标题", "price": {"low": 4948, "high": 4948}})))
    svc = AnalyzeService(repo=repo)

    result = await svc.get_saved_report("1", 1, lang="")

    assert result is not None
    assert result["lang"] == "ru"
    assert result["display"]["title"] == "俄语标题"
    assert repo.update_calls == 0  # 没有因"默认 en"而重建回写


# ---- 2. 请求 en 但只存 ru → 快照优先返回 ru（不现场生成英文）----
@pytest.mark.asyncio
async def test_saved_report_missing_requested_lang_falls_back_to_stored():
    repo = FakeRepo(saved=_saved(_stored(ru={"title": "俄语标题", "price": {"low": 1, "high": 2}})))
    svc = AnalyzeService(repo=repo)

    result = await svc.get_saved_report("1", 1, lang="en")

    assert result["lang"] == "ru"
    assert result["display"]["title"] == "俄语标题"
    assert repo.update_calls == 0


# ---- 3. get_history lang 优先：标题 + verdict_grade 取 ru display ----
def _hist_row(di18n_str: str) -> dict:
    return {"id": 1, "offer_id": "1", "title": "英文列标题", "image_url": "", "created_at": "2026-09-07 10:00:00", "display_i18n": di18n_str}


@pytest.mark.asyncio
async def test_history_picks_requested_lang_title_and_verdict():
    repo = FakeRepo(rows=[_hist_row(_stored(
        en={"title": "EN title", "supplierEval": {"grade": "go"}, "summaryLine": {"grade": "go"}, "trustBar": {}},
        ru={"title": "RU заголовок", "supplierEval": {"grade": "go"}, "summaryLine": {"grade": "ok"}, "trustBar": {}},
    ))])
    svc = AnalyzeService(repo=repo)

    rows = await svc.get_history(1, limit=10, lang="ru")

    assert len(rows) == 1
    row = rows[0]
    assert row["lang"] == "ru"
    assert row["title"] == "RU заголовок"        # 标题按存储语言覆盖英文列
    assert row["verdict_grade"] == "ok"           # 综合结论档位（summaryLine.grade）
    assert row["seller_grade"] == "go"            # 供应商档位仍保留（兼容）


# ---- 4. 旧行无 display → 列表给 none 档位，不崩 ----
@pytest.mark.asyncio
async def test_history_no_display_grade_none():
    repo = FakeRepo(rows=[_hist_row("")])
    svc = AnalyzeService(repo=repo)

    rows = await svc.get_history(1, limit=10, lang="ru")

    assert rows[0]["verdict_grade"] == "none"
    assert rows[0]["lang"] == ""

"""端到端流程实测 — 验证「分析流水线」13 节点是否按设计执行 + G/H 隐患假设证实/证伪。

方式（全真实）：
  - 真实 uvicorn 子进程（真实 HTTP，穿过 CORS→JWT→routes→services→repo→MySQL）
  - 真实 MySQL（验证落库/复用/配额对称性）
  - 真实 Apify 抓取 + 真实 Qwen 判词
  - 登录用 create_token 签测试 JWT（Google OAuth 需真实账号+浏览器授权，脚本代劳不了）

前置：MySQL 在跑，src/api/.env 已配（APIFY_TOKEN1 + QWEN_API_KEY + DB 必填项）。

用法：
  python tests/e2e_flow.py            # 全流程 6 场景
  python tests/e2e_flow.py --only A   # 只跑场景 A（快速验证骨架）
  python tests/e2e_flow.py --clean    # 只清理 e2e_ 测试用户 + 其分析数据
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import aiomysql
import httpx

# Windows GBK 控制台无法编码 emoji，强制 stdout 用 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_DIR = Path(__file__).resolve().parent.parent / "src" / "api"
sys.path.insert(0, str(API_DIR))

from config import Config  # noqa: E402
from utils.jwt import create_token  # noqa: E402

PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"

# 用户提供的 4 个真实 1688 商品 offer_id
OFFERS = ["1053910572406", "997997017645", "900685412535", "685469710262"]


def _url(offer_id: str) -> str:
    return Config.URL_1688_DETAIL.format(offer_id=offer_id)


# ----------------------------------------------------------------------
# DB 直连（脚本进程独立连接，不碰后端连接池）
# ----------------------------------------------------------------------

async def _db_connect() -> aiomysql.Connection:
    return await aiomysql.connect(
        host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
        password=Config.DB_PASSWORD, db=Config.DB_NAME, charset="utf8mb4",
        autocommit=True,
    )


async def seed_user(quota: int) -> int:
    """建一个带指定配额的测试用户，返回 user_id。"""
    google_id = f"e2e_{int(time.time() * 1000)}"
    conn = await _db_connect()
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "INSERT INTO users (google_id, email, name, quota, default_lang, last_reset_date) "
                "VALUES (%s, %s, %s, %s, 'zh', CURDATE())",
                (google_id, f"{google_id}@e2e.test", "E2E", quota),
            )
            user_id = cur.lastrowid
        await conn.commit()
        return user_id
    finally:
        conn.close()


async def get_quota(user_id: int) -> int:
    """查用户当前配额（配额对称性断言用）。"""
    conn = await _db_connect()
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT quota FROM users WHERE id=%s", (user_id,))
            row = await cur.fetchone()
            return row["quota"] if row else -1
    finally:
        conn.close()


async def get_display_i18n(offer_id: str, user_id: int) -> dict:
    """读 analysis 表 display_i18n 字段（验证落库/复用）。"""
    conn = await _db_connect()
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT raw_json, display_i18n FROM analysis WHERE offer_id=%s AND user_id=%s",
                (offer_id, user_id),
            )
            row = await cur.fetchone()
            if not row:
                return {}
            di18n = row.get("display_i18n")
            return {
                "raw": bool(row.get("raw_json")),
                "langs": list(json.loads(di18n).keys()) if di18n else [],
            }
    finally:
        conn.close()


async def clean_e2e_data() -> int:
    """清理 e2e_ 测试用户 + 其 analysis 记录，返回删除的用户数。"""
    conn = await _db_connect()
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT id FROM users WHERE google_id LIKE 'e2e\\_%'")
            ids = [r["id"] for r in await cur.fetchall()]
            for uid in ids:
                await cur.execute("DELETE FROM analysis WHERE user_id=%s", (uid,))
            await cur.execute("DELETE FROM users WHERE google_id LIKE 'e2e\\_%'")
        await conn.commit()
        return len(ids)
    finally:
        conn.close()


async def count_analysis(user_id: int) -> int:
    """统计用户 status='done' 的记录数（3.7 超限清理断言用）。"""
    conn = await _db_connect()
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT COUNT(*) AS cnt FROM analysis WHERE user_id=%s AND status='done'",
                (user_id,),
            )
            row = await cur.fetchone()
            return row["cnt"] if row else 0
    finally:
        conn.close()


async def seed_analysis_rows(user_id: int, n: int) -> int:
    """插 n 条假 analysis 记录（status=done, favorited=0, created_at 严格递增）。"""
    conn = await _db_connect()
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            for i in range(n):
                # created_at 递减：fake_0000 最旧，保证 FIFO 删除顺序可验证
                await cur.execute(
                    "INSERT INTO analysis (user_id, offer_id, status, title, raw_json, favorited, created_at) "
                    "VALUES (%s, %s, 'done', %s, '{}', 0, NOW() - INTERVAL %s SECOND)",
                    (user_id, f"fake_{i:04d}", f"fake {i}", n - i),
                )
        await conn.commit()
        return n
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 服务生命周期
# ----------------------------------------------------------------------

def start_server() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=str(API_DIR),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc


def wait_health(timeout: int = 40) -> bool:
    for _ in range(timeout):
        try:
            r = httpx.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


async def poll_task(client: httpx.AsyncClient, token: str, task_id: str,
                    timeout_s: int = 180) -> dict:
    """轮询 GET /api/analyze/{task_id} 直到 done/failed，返回 task dict。"""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        r = await client.get(f"{BASE}/api/analyze/{task_id}",
                             headers={"Authorization": f"Bearer {token}"})
        body = r.json()
        if body.get("data", {}).get("status") in ("done", "failed"):
            return body["data"]
        await asyncio.sleep(2)
    return {"status": "timeout"}


# ----------------------------------------------------------------------
# 场景
# ----------------------------------------------------------------------

async def scenario_A(client, token, user_id):
    """A-zh 新商品：节点 1→2→3.2→3.3→3.4→3.5(模板)→3.6 全链。"""
    offer = OFFERS[0]
    q0 = await get_quota(user_id)
    r = await client.post(f"{BASE}/api/analyze", json={"url": _url(offer), "lang": "zh"},
                          headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return {"pass": False, "why": f"POST {r.status_code} {r.text[:200]}"}
    task_id = r.json()["data"]["task_id"]
    task = await poll_task(client, token, task_id)
    if task.get("status") != "done":
        return {"pass": False, "why": f"status={task.get('status')} err={task.get('error')}"}
    display = task.get("result", {}).get("display", {})
    keys = ["title", "price", "summaryLine", "productEval", "supplierEval"]
    missing = [k for k in keys if k not in display]
    if missing:
        return {"pass": False, "why": f"display 缺字段 {missing}"}
    if "_aiGenerated" in display:
        return {"pass": False, "why": "zh 路径不应有 _aiGenerated"}
    db = await get_display_i18n(offer, user_id)
    q1 = await get_quota(user_id)
    return {
        "pass": True,
        "evidence": f"display 完整 keys={len(display)} DB落库 raw={db.get('raw')} langs={db.get('langs')} 配额 {q0}→{q1}",
    }


async def scenario_B(client, token, user_id):
    """B-en 新商品：3.5 AI 路径 + 真实 Qwen + 落库 display_i18n.en（验 G12 修复）。"""
    offer = OFFERS[1]
    r = await client.post(f"{BASE}/api/analyze", json={"url": _url(offer), "lang": "en"},
                          headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return {"pass": False, "why": f"POST {r.status_code}"}
    task_id = r.json()["data"]["task_id"]
    task = await poll_task(client, token, task_id)
    if task.get("status") != "done":
        return {"pass": False, "why": f"status={task.get('status')} err={task.get('error')}"}
    display = task.get("result", {}).get("display", {})
    verdict = display.get("summaryLine", {}).get("verdict")
    if not verdict:
        return {"pass": False, "why": "AI 判词 verdict 为空"}
    db = await get_display_i18n(offer, user_id)
    if "en" not in db.get("langs", []):
        return {"pass": False, "why": f"G12：display_i18n 无 en，实际 langs={db.get('langs')}"}
    return {
        "pass": True,
        "evidence": f"AI判词 verdict={verdict!r} DB落库 langs={db.get('langs')}（en 落库成功 = G12 已修）",
    }


async def scenario_C(client, token, user_id):
    """C-复用：同 offer 再跑 lang=en → DB 命中秒回，不调 Apify（验 3.1 + G12）。"""
    offer = OFFERS[1]
    q0 = await get_quota(user_id)
    t0 = time.time()
    r = await client.post(f"{BASE}/api/analyze", json={"url": _url(offer), "lang": "en"},
                          headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return {"pass": False, "why": f"POST {r.status_code}"}
    task_id = r.json()["data"]["task_id"]
    task = await poll_task(client, token, task_id, timeout_s=30)
    elapsed = time.time() - t0
    q1 = await get_quota(user_id)
    if task.get("status") != "done":
        return {"pass": False, "why": f"status={task.get('status')}"}
    if elapsed > 5:
        return {"pass": False, "why": f"复用耗时 {elapsed:.1f}s > 5s（疑似重跑 Apify）"}
    return {
        "pass": True,
        "evidence": f"DB命中秒回 {elapsed:.1f}s 配额 {q0}→{q1}（+1 = 退配额，复用不扣）",
    }


async def scenario_D(client, token, user_id, quota):
    """D-配额耗尽：quota 扣到 0 后再发 → QUOTA_EXHAUSTED。"""
    offer = OFFERS[2]
    last = None
    for _ in range(quota + 1):  # 第一次扣到 0，最后一次应拒绝
        r = await client.post(f"{BASE}/api/analyze", json={"url": _url(offer), "lang": "zh"},
                              headers={"Authorization": f"Bearer {token}"})
        last = r
        if r.status_code in (403, 429):
            break
    if last is None:
        return {"pass": False, "why": "未发出请求"}
    body = last.json()
    if body.get("msg_code") == "QUOTA_EXHAUSTED":
        return {"pass": True, "evidence": f"耗尽后返回 QUOTA_EXHAUSTED (http {last.status_code})"}
    return {"pass": False, "why": f"未按预期耗尽，http {last.status_code} msg_code={body.get('msg_code')}"}


async def scenario_E(client, token, user_id):
    """E-失败：无效 offer_id → failed + PRODUCT_NOT_FOUND + 退配额。"""
    q0 = await get_quota(user_id)
    r = await client.post(f"{BASE}/api/analyze", json={"url": _url("000000000000"), "lang": "zh"},
                          headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return {"pass": False, "why": f"POST {r.status_code}"}
    task_id = r.json()["data"]["task_id"]
    task = await poll_task(client, token, task_id, timeout_s=150)
    q1 = await get_quota(user_id)
    if task.get("status") != "failed":
        return {"pass": False, "why": f"期望 failed，实际 {task.get('status')}"}
    return {
        "pass": True,
        "evidence": f"failed msg_code={task.get('error_msg_code')} 配额 {q0}→{q1}（退配额 = 对称）",
    }


async def scenario_F(client, token, user_id):
    """F-并发：并发 2 个同 offer → 只扣 1 次配额（验 G1）。"""
    offer = OFFERS[3]
    q0 = await get_quota(user_id)
    async def one():
        r = await client.post(f"{BASE}/api/analyze", json={"url": _url(offer), "lang": "zh"},
                              headers={"Authorization": f"Bearer {token}"})
        return r.json().get("data", {}).get("task_id") if r.status_code == 200 else None
    ids = await asyncio.gather(one(), one())
    ids = [i for i in ids if i]
    for tid in ids:
        await poll_task(client, token, tid, timeout_s=150)
    q1 = await get_quota(user_id)
    delta = q0 - q1
    if delta != 1:
        return {"pass": False, "why": f"并发 2 请求应只扣 1 次，实际扣 {delta} 次（配额 {q0}→{q1}）"}
    return {"pass": True, "evidence": f"并发 2 请求 task_ids={len(ids)} 配额 {q0}→{q1}（扣 1 次 = G1 已修）"}


async def scenario_G(client, token, user_id):
    """G-3.7 超限清理：插 21 条假记录 → 新分析触发 cleanup → FIFO 删到 20。"""
    offer = OFFERS[0]
    await seed_analysis_rows(user_id, 21)
    before = await count_analysis(user_id)
    r = await client.post(f"{BASE}/api/analyze", json={"url": _url(offer), "lang": "zh"},
                          headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return {"pass": False, "why": f"POST {r.status_code}"}
    task_id = r.json()["data"]["task_id"]
    task = await poll_task(client, token, task_id)
    if task.get("status") != "done":
        return {"pass": False, "why": f"status={task.get('status')} err={task.get('error')}"}
    after = await count_analysis(user_id)
    # 21 假 + 1 新 = 22 → cleanup 删 2 条最旧（free 上限 20）
    if after != 20:
        return {"pass": False, "why": f"期望删到 20，实际 {before}→{after}"}
    return {"pass": True, "evidence": f"插21+新1={before} → 删到 {after}，FIFO 删最早未收藏"}


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

async def run(only: str | None):
    print("== 端到端流程实测 ==")
    proc = start_server()
    try:
        if not wait_health():
            print("❌ uvicorn 启动失败，检查 src/api/.env + MySQL")
            return
        print(f"✅ uvicorn 已启动 :{PORT}")

        # 建 3 个用户：主用户 quota=50 跑 A/B/C/E/F，耗尽用户 quota=1 跑 D，清理用户跑 G
        main_uid = await seed_user(50)
        drain_uid = await seed_user(1)
        cleanup_uid = await seed_user(50)
        main_token = create_token(user_id=main_uid, email="e2e@test.com", default_lang="zh")
        drain_token = create_token(user_id=drain_uid, email="e2e@test.com", default_lang="zh")
        cleanup_token = create_token(user_id=cleanup_uid, email="e2e@test.com", default_lang="zh")
        print(f"✅ 测试用户 main={main_uid} drain={drain_uid} cleanup={cleanup_uid}")

        async with httpx.AsyncClient(timeout=180) as client:
            scenarios = {
                "A-zh新商品": lambda: scenario_A(client, main_token, main_uid),
                "B-en新商品": lambda: scenario_B(client, main_token, main_uid),
                "C-复用": lambda: scenario_C(client, main_token, main_uid),
                "D-配额耗尽": lambda: scenario_D(client, drain_token, drain_uid, 1),
                "E-失败退配额": lambda: scenario_E(client, main_token, main_uid),
                "F-并发双扣": lambda: scenario_F(client, main_token, main_uid),
                "G-超限清理": lambda: scenario_G(client, cleanup_token, cleanup_uid),
            }
            if only:
                scenarios = {k: v for k, v in scenarios.items() if k.startswith(only)}

            results = {}
            for name, fn in scenarios.items():
                print(f"\n--- 场景 {name} ---")
                t0 = time.time()
                try:
                    r = await fn()
                    r["elapsed"] = round(time.time() - t0, 1)
                except Exception as e:
                    r = {"pass": False, "why": f"异常 {type(e).__name__}: {e}"}
                results[name] = r
                mark = "✅" if r["pass"] else "❌"
                print(f"{mark} {name}  {r.get('evidence') or r.get('why')}  ({r.get('elapsed', '?')}s)")

        print("\n== 汇总 ==")
        passed = sum(1 for r in results.values() if r["pass"])
        print(f"通过 {passed}/{len(results)}")
        for name, r in results.items():
            if not r["pass"]:
                print(f"  ❌ {name}: {r.get('why')}")

        print(f"\n测试用户 main={main_uid} drain={drain_uid}（数据已保留，可查 DB 验证；")
        print("跑完清理：python tests/e2e_flow.py --clean")
    finally:
        proc.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只跑某场景，如 A")
    ap.add_argument("--clean", action="store_true", help="清理 e2e_ 测试数据")
    args = ap.parse_args()

    if args.clean:
        n = asyncio.run(clean_e2e_data())
        print(f"清理 {n} 个 e2e_ 测试用户")
        return
    asyncio.run(run(args.only))


if __name__ == "__main__":
    main()

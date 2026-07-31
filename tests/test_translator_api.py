"""快速测试 Qwen3 翻译 API — 试不同模型名。"""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "api"))

import httpx
from config import Config

BASE = Config.QWEN_API_BASE  # 验证过正确
URL = f"{BASE}/chat/completions"


async def try_model(model_name: str):
    print(f"\n--- Model: {model_name} ---")
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "Translate Chinese to English. Return ONLY JSON."},
            {"role": "user", "content": '{"title": "韩版不锈钢项链女"}'},
        ],
        "temperature": 0.1,
        "max_tokens": 128,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                URL,
                headers={
                    "Authorization": f"Bearer {Config.QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            body = resp.json()
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"OK! Result: {content[:200]}")
            return True
        else:
            print(f"Response: {resp.text[:300]}")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False


async def main():
    print(f"Base URL: {BASE}")
    print(f"API Key prefix: {Config.QWEN_API_KEY[:20]}...")

    # 百炼常见模型名
    candidates = [
        "qwen-flash",
        "qwen-plus",
        "qwen-max",
        "qwen-turbo",
        "qwen3-flash",
        "qwen2.5-7b-instruct",
        "Qwen3-Flash",
        "qwen3-flash-chat",
        "Qwen3.7-Flash",
    ]

    for name in candidates:
        ok = await try_model(name)
        if ok:
            print(f"\n>>> CORRECT MODEL: {name}")
            print(f">>> Update .env: QWEN_MODEL={name}")
            return
        await asyncio.sleep(0.3)

    print("\nAll model names failed. Checking available models...")
    # 尝试 list models
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{BASE}/models",
                headers={"Authorization": f"Bearer {Config.QWEN_API_KEY}"},
            )
        print(f"List models status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("id", str(m)) for m in data.get("data", [])]
            print(f"Available models: {models}")
        else:
            print(f"Response: {resp.text[:500]}")
    except Exception as e:
        print(f"List models error: {e}")


if __name__ == "__main__":
    asyncio.run(main())

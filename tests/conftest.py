"""pytest 全局配置：把 src/api 注入 sys.path + 清理 analyze_svc 模块级全局状态。

后端代码用无包前缀 import（from config import Config），测试需能从 src/api 解析。
"""

import sys
from pathlib import Path

import pytest

_API_DIR = Path(__file__).resolve().parent.parent / "src" / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))


@pytest.fixture(autouse=True)
def _clean_analyze_globals():
    """每个用例前后清空 analyze_svc 的全局容器，隔离测试间状态。"""
    import services.analyze_svc as analyze_svc

    analyze_svc._pending.clear()
    analyze_svc._tasks.clear()
    analyze_svc._fail_count.clear()
    yield
    analyze_svc._pending.clear()
    analyze_svc._tasks.clear()
    analyze_svc._fail_count.clear()

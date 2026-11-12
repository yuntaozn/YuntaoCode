"""通过 Node 执行真实前端函数，覆盖流连接和后台终态不一致的行为。"""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_panel_stream_lifecycle():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("panel_stream_lifecycle.test.cjs"))],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

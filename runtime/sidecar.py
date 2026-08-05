from __future__ import annotations

import os
import sys


def _configure_stdio() -> None:
    """确保 Windows 上桌面壳能够解码 sidecar 输出。"""

    os.environ.setdefault("PYTHONIOENCODING", "utf-8:replace")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


_configure_stdio()

from runtime.app import main


if __name__ == "__main__":
    main()

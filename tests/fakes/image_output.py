"""无第三方依赖的微型 PNG 工具输出，用于媒体边界测试。"""

import base64
import struct
import zlib


def image_output():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress((b"\0" + b"\0\0\0" * 4) * 3)) + chunk(b"IEND", b""))
    return {"mcp_content": [{"type": "image", "mimeType": "image/png", "data": base64.b64encode(png).decode("ascii")}]}

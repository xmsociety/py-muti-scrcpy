"""公共方法"""
import struct
from typing import Optional

import cv2
import numpy as np
from loguru import logger


class StructPack:
    HeadLenth = 28

    @staticmethod
    def struct_pack(len_data: int, serialno: str) -> tuple[int, bytes]:
        pack = struct.pack("l20s", len_data, serialno.encode())
        len_pack = len(pack)
        if len_pack != StructPack.HeadLenth:
            return 0, b""
        return len_pack, pack

    @staticmethod
    def struct_unpack(bdata: bytes) -> tuple[int, str]:
        unpack = struct.unpack("l20s", bdata[: StructPack.HeadLenth])
        len_data = unpack[0]
        serialno = unpack[1].replace(b"\x00", b"").decode()
        return len_data, serialno


def unpack(format: str, bdata: bytes) -> Optional[tuple]:
    """8 字节包则按 ``format`` 解包，否则返回 ``None``。

    旧实现遇到任何异常都静默吞掉；现在只对 ``struct.error`` 兜底，其他错误
    （例如 format 写错）应该正常向上抛出。
    """
    if len(bdata) != 8:
        return None
    try:
        return struct.unpack(format, bdata)
    except struct.error as err:
        logger.warning(f"unpack failed: {err}")
        return None


def imencode(img) -> bytes:
    ext = ".png"
    sign, uint8img = cv2.imencode(ext=ext, img=img)
    return uint8img.tobytes() if sign else b""


def imdecode(buint8img: bytes) -> Optional[np.ndarray]:
    try:
        uint8img = np.frombuffer(buint8img, np.uint8)
        return cv2.imdecode(uint8img, cv2.IMREAD_COLOR)
    except Exception as err:
        logger.warning(f"imdecode failed: {err}")
        return None


import json
from socket import socket
from typing import Optional

import numpy as np
from loguru import logger
from pydantic import BaseModel, ConfigDict

from .utils import imdecode, imencode


class ServerInfo(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    host: str
    port: int
    server: Optional[socket] = None


class ReqInfoSmallImg(BaseModel):
    """
    tips: 小于1024的可以直接发送,一般需要分包发送
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    utime: int
    img: np.ndarray
    split_by: bytes = b"utime_img"

    def encode(self):
        endata = b""
        butime = str(self.utime).encode()
        bimg = imencode(self.img)
        if bimg:
            endata = self.split_by.join([butime, bimg])
        else:
            logger.warning(f"ReqInfoSmallImg img can't encode: {self.img.shape})")
        return endata

    @staticmethod
    def decode(bdata):
        data = None
        blist = bdata.split(ReqInfoSmallImg(utime=0, img=np.ndarray(0)).split_by)
        if len(blist) == 2:
            btime, buint8img = blist
            utime = int(btime.decode())
            img = imdecode(buint8img)
            data = ReqInfoSmallImg(utime=utime, img=img)
        return data


class RspInfo(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    utime: int
    rst: dict
    split_by: bytes = b"utime_rst"

    def encode(self) -> bytes:
        endata = b""
        butime = str(self.utime).encode()
        brst = json.dumps(self.rst).encode()

        endata = self.split_by.join([butime, brst])
        return endata

    @staticmethod
    def decode(bdata):
        data = None
        blist = bdata.split(RspInfo(utime=0, rst={}).split_by)
        if len(blist) == 2:
            btime, brst = blist
            utime = int(btime.decode())
            rst = json.loads(brst.decode())
            data = RspInfo(utime=utime, rst=rst)
        return data


if __name__ == "__main__":
    import os
    import time

    def test_reqinfo():
        img_path = os.path.join(os.environ.get("HOME"), "Desktop", "nani.jpeg")
        img = cv2.imread(img_path)
        utime = int(time.time())
        req = ReqInfoSmallImg(utime=utime, img=img)
        endata = req.encode()
        decode = ReqInfoSmallImg.decode(endata)
        assert decode.utime == req.utime and decode.img.all() == req.img.all()

    def test_rspinfo():
        utime = int(time.time())
        req = RspInfo(utime=utime, rst={"test": {"result": [0, 0], "confidence": 1.0}})
        endata = req.encode()
        decode = RspInfo.decode(endata)
        assert req == decode

    test_reqinfo()
    test_rspinfo()

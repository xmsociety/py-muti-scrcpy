"""
Copyright (c) 2026 IanVzs. All rights reserved.
"""

import inspect
import pathlib
import pickle

import pytest
from adbutils import AdbError

from scrcpy import Client, MutiClient
from tests.utils import FakeStream

DEVICE_NAME = b"test" + b"\x00" * 60
VIDEO_HEADER = b"h264" + b"\x00\x00\x07\x80" + b"\x00\x00\x04\x38"


class FakeADBDevice:
    """Same minimal stub as ``tests/test_core.py`` to avoid hitting real ADB."""

    def __init__(self, data, wait=0):
        self.data = data
        self.__wait = wait

    @staticmethod
    def push(a, b=None):
        pass

    @staticmethod
    def shell(a, stream=False):
        if stream:
            return FakeStream([b"\x00" * 128])
        # Pretend the on-device jar size never matches → always push.
        return ""

    def create_connection(self, a, b):
        if self.__wait > 0:
            self.__wait -= 1
            raise AdbError()
        return FakeStream(self.data.pop(0))


def test_muticlient_inherits_client():
    """MutiClient 应该是 Client 的子类，而不是平行实现。"""
    assert issubclass(MutiClient, Client)


def test_multiclient_alias():
    """``MultiClient`` 是修正后的拼写，必须与 ``MutiClient`` 指向同一类。"""
    from scrcpy import MultiClient

    assert MultiClient is MutiClient


def test_muticlient_start_is_generator():
    """``MutiClient.start`` 必须保持生成器协议，否则 worker 的
    ``for frame in client.start():`` 会立即崩溃。"""
    assert inspect.isgeneratorfunction(MutiClient.start)


def test_muticlient_default_bitrate_overridden():
    """子类对 bitrate 默认值的覆盖不能丢。"""
    sig = inspect.signature(MutiClient.__init__)
    assert sig.parameters["bitrate"].default == 16000000


def test_muticlient_yields_frames_then_exits_on_socket_close():
    """跑一遍 fake video pipeline，验证 yield 行为与 OSError 路径。"""
    video_data = pickle.load(
        (pathlib.Path(__file__).parent / "test_video_data.pkl").resolve().open("rb")
    )
    data = [
        # None 触发一次 BlockingIOError → yield None；最后 b"OSError" 触发 OSError
        [b"\x00", DEVICE_NAME, VIDEO_HEADER, None] + video_data + [b"OSError"],
        [],
    ]
    client = MutiClient(device=FakeADBDevice(data))
    received: list = []

    with pytest.raises(OSError):
        for frame in client.start():
            received.append(frame)
            if len(received) >= 5:
                # 提前 stop，让生成器在下一轮退出
                client.stop()

    assert received[0] is None  # 首个 yield 应该是 BlockingIOError 占位
    # 至少能收到一帧解码后的画面
    assert any(getattr(f, "shape", None) == (800, 368, 3) for f in received)

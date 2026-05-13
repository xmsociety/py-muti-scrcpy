import os
import socket
import struct
import threading
import time
from time import sleep
from typing import Any, Callable, Iterator, Optional, Tuple, Union

import cv2
import numpy as np
from adbutils import AdbDevice, AdbError, Network, adb
from av.codec import CodecContext

from .const import EVENT_FRAME, EVENT_INIT, LOCK_SCREEN_ORIENTATION_UNLOCKED
from .control import ControlSender

SCRCPY_SERVER_VERSION = "3.3.4"


class Client:
    """Listener-style scrcpy client.

    See :class:`scrcpy.muti_core.Client` (a.k.a. ``MutiClient``) for the
    generator-style variant used by the worker layer.
    """

    def __init__(
        self,
        device: Optional[Union[AdbDevice, str, any]] = None,
        max_width: int = 0,
        bitrate: int = 8000000,
        max_fps: int = 0,
        flip: bool = False,
        block_frame: bool = False,
        stay_awake: bool = False,
        lock_screen_orientation: int = LOCK_SCREEN_ORIENTATION_UNLOCKED,
        connection_timeout: int = 3000,
    ):
        """
        Create a scrcpy client, this client won't be started until you call the start function

        Args:
            device: Android device, select first one if none, from serial if str
            max_width: frame width that will be broadcast from android server
            bitrate: bitrate
            max_fps: maximum fps, 0 means not limited (supported after android 10)
            flip: flip the video
            block_frame: only return nonempty frames, may block cv2 render thread
            stay_awake: keep Android device awake
            lock_screen_orientation: lock screen orientation, LOCK_SCREEN_ORIENTATION_*
            connection_timeout: timeout for connection, unit is ms
        """

        if device is None:
            devices = adb.device_list()
            if not devices:
                raise ConnectionError("No ADB devices found")
            device = devices[0]
        elif isinstance(device, str):
            device = adb.device(serial=device)

        self.device = device
        self.listeners = dict(frame=[], init=[])

        # User accessible
        self.last_frame: Optional[np.ndarray] = None
        self.resolution: Optional[Tuple[int, int]] = None
        self.device_name: Optional[str] = None
        self.control = ControlSender(self)

        # Params
        self.flip = flip
        self.max_width = max_width
        self.bitrate = bitrate
        self.max_fps = max_fps
        self.block_frame = block_frame
        self.stay_awake = stay_awake
        self.lock_screen_orientation = lock_screen_orientation
        self.connection_timeout = connection_timeout

        # Need to destroy. Single-underscore so subclasses can access them
        # without triggering Python's name mangling.
        self.alive = False
        self._server_stream: Optional[Any] = None
        self._video_socket: Optional[socket.socket] = None
        self.control_socket: Optional[socket.socket] = None
        self.control_socket_lock = threading.Lock()

    @staticmethod
    def _recv_exact(sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ConnectionError("Socket closed while reading scrcpy metadata")
            data.extend(chunk)
        return bytes(data)

    def _init_server_connection(self) -> None:
        """
        Connect to android server, there will be two sockets, video and control socket.
        This method will set: video_socket, control_socket, resolution variables
        """
        for _ in range(self.connection_timeout // 100):
            try:
                self._video_socket = self.device.create_connection(
                    Network.LOCAL_ABSTRACT, "scrcpy"
                )
                break
            except AdbError:
                sleep(0.1)
                pass
        else:
            raise ConnectionError(
                f"Failed to connect scrcpy-server after {self.connection_timeout / 1000:.1f} seconds"
            )

        dummy_byte = self._video_socket.recv(1)
        if not len(dummy_byte) or dummy_byte != b"\x00":
            raise ConnectionError("Did not receive Dummy Byte!")

        self.control_socket = self.device.create_connection(
            Network.LOCAL_ABSTRACT, "scrcpy"
        )
        self.device_name = (
            self._recv_exact(self._video_socket, 64).decode("utf-8").rstrip("\x00")
        )
        if not len(self.device_name):
            raise ConnectionError("Did not receive Device Name!")

        # scrcpy v3 sends codec id + video width + video height before raw H.264 data.
        _, width, height = struct.unpack(
            ">III", self._recv_exact(self._video_socket, 12)
        )
        self.resolution = (width, height)
        self._video_socket.setblocking(False)

    _SERVER_REMOTE_PATH = "/data/local/tmp/scrcpy-server.jar"

    def _remote_jar_size(self) -> Optional[int]:
        """Return ``stat -c %s`` for the remote jar, or ``None`` if missing.

        Some Android ROMs ship a ``stat`` that doesn't accept ``-c``; in that
        case we fall back to ``wc -c < path`` which is universally available
        on busybox / toybox.
        """
        for cmd in (
            f"stat -c %s {self._SERVER_REMOTE_PATH} 2>/dev/null",
            f"wc -c < {self._SERVER_REMOTE_PATH} 2>/dev/null",
        ):
            try:
                out = self.device.shell(cmd).strip()
            except Exception:
                continue
            if out.isdigit():
                return int(out)
        return None

    def _deploy_server(self) -> None:
        """
        Deploy server to android device. Skips push when the on-device jar is
        already the same size as the bundled one — multi-device cold-starts
        spend a non-trivial chunk of wall time inside ``adb push`` otherwise.
        """
        server_root = os.path.abspath(os.path.dirname(__file__))
        server_file_path = server_root + "/scrcpy-server.jar"
        local_size = os.path.getsize(server_file_path)
        if self._remote_jar_size() != local_size:
            self.device.push(server_file_path, self._SERVER_REMOTE_PATH)
        self._server_stream = self.device.shell(
            [
                "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
                "app_process",
                "/",
                "com.genymobile.scrcpy.Server",
                SCRCPY_SERVER_VERSION,
                "log_level=info",
                "video=true",
                "audio=false",
                "video_codec=h264",
                f"max_size={self.max_width}",
                f"video_bit_rate={self.bitrate}",
                f"max_fps={self.max_fps}",
                "tunnel_forward=true",
                "control=true",
                "display_id=0",
                "show_touches=false",
                f"stay_awake={'true' if self.stay_awake else 'false'}",
                "power_off_on_close=false",
                "clipboard_autosync=false",
                "downsize_on_error=true",
                "cleanup=true",
                "power_on=true",
                "send_device_meta=true",
                "send_frame_meta=false",
                "send_dummy_byte=true",
                "send_codec_meta=true",
            ],
            stream=True,
        )
        # Wait for server to start
        self._server_stream.read(10)

    def _read_server_output(self) -> str:
        if self._server_stream is None:
            return ""

        conn = getattr(self._server_stream, "conn", None)
        old_timeout = None
        if conn is not None and hasattr(conn, "gettimeout"):
            old_timeout = conn.gettimeout()
            conn.settimeout(0.2)

        try:
            output = self._server_stream.read(4096)
        except Exception:
            return ""
        finally:
            if conn is not None and old_timeout is not None:
                conn.settimeout(old_timeout)

        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return str(output)

    def start(self, threaded: bool = False) -> None:
        """
        Start listening video stream

        Args:
            threaded: Run stream loop in a different thread to avoid blocking
        """
        assert self.alive is False

        try:
            self._deploy_server()
            self._init_server_connection()
        except Exception:
            self.stop()
            raise
        self.alive = True
        self._send_to_listeners(EVENT_INIT)

        if threaded:
            threading.Thread(target=self.__stream_loop, daemon=True).start()
        else:
            self.__stream_loop()

    def stop(self) -> None:
        """
        Stop listening (both threaded and blocked)
        """
        self.alive = False
        if self._server_stream is not None:
            try:
                self._server_stream.close()
            except (OSError, AttributeError):
                pass
            self._server_stream = None
        if self.control_socket is not None:
            try:
                self.control_socket.close()
            except (OSError, AttributeError):
                pass
            self.control_socket = None
        if self._video_socket is not None:
            try:
                self._video_socket.close()
            except (OSError, AttributeError):
                pass
            self._video_socket = None

    def _iter_frames(self) -> Iterator[Optional[np.ndarray]]:
        """Yield decoded frames (or ``None`` placeholders) until the socket
        closes. Subclasses can consume this directly to expose generator-style
        APIs while keeping codec/socket handling in one place.

        Raises ``ConnectionError`` when the scrcpy-server pipe goes away and
        ``OSError`` for any other socket failure that happens while ``alive``.
        """
        codec = CodecContext.create("h264", "r")
        while self.alive:
            try:
                raw_h264 = self._video_socket.recv(0x10000)
                if not raw_h264:
                    self.alive = False
                    server_output = self._read_server_output()
                    message = "Video socket closed; scrcpy-server may have crashed"
                    if server_output:
                        message = f"{message}\n{server_output}"
                    raise ConnectionError(message)
                packets = codec.parse(raw_h264)
                for packet in packets:
                    frames = codec.decode(packet)
                    for frame in frames:
                        frame = frame.to_ndarray(format="bgr24")
                        if self.flip:
                            frame = cv2.flip(frame, 1)
                        self.last_frame = frame
                        self.resolution = (frame.shape[1], frame.shape[0])
                        yield frame
            except BlockingIOError:
                time.sleep(0.01)
                if not self.block_frame:
                    yield None
            except OSError as e:
                if self.alive:
                    raise e
                return

    def __stream_loop(self) -> None:
        """Listener-style adapter: dispatch every frame to ``EVENT_FRAME``."""
        for frame in self._iter_frames():
            self._send_to_listeners(EVENT_FRAME, frame)

    def add_listener(self, cls: str, listener: Callable[..., Any]) -> None:
        """
        Add a video listener

        Args:
            cls: Listener category, support: init, frame
            listener: A function to receive frame np.ndarray
        """
        self.listeners[cls].append(listener)

    def remove_listener(self, cls: str, listener: Callable[..., Any]) -> None:
        """
        Remove a video listener

        Args:
            cls: Listener category, support: init, frame
            listener: A function to receive frame np.ndarray
        """
        self.listeners[cls].remove(listener)

    def _send_to_listeners(self, cls: str, *args, **kwargs) -> None:
        """
        Send event to listeners

        Args:
            cls: Listener type
            *args: Other arguments
            *kwargs: Other arguments
        """
        for fun in self.listeners[cls]:
            fun(*args, **kwargs)

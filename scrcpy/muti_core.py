import os
import socket
import struct
import threading
import time
from io import BufferedIOBase, BytesIO
from time import sleep
from typing import Any, Callable, Optional, Tuple, Union

import av
import cv2
import numpy as np
from adbutils import AdbDevice, AdbError, Network, adb
from av.codec import CodecContext

from .const import EVENT_FRAME, EVENT_INIT, LOCK_SCREEN_ORIENTATION_UNLOCKED
from .control import ControlSender

SCRCPY_SERVER_VERSION = "3.3.4"


class Client:
    def __init__(
        self,
        device: Optional[Union[AdbDevice, str, any]] = None,
        max_width: int = 0,
        bitrate: int = 16000000,
        max_fps: int = 0,
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
            block_frame: only return nonempty frames, may block cv2 render thread
            stay_awake: keep Android device awake
            lock_screen_orientation: lock screen orientation, LOCK_SCREEN_ORIENTATION_*
            connection_timeout: timeout for connection, unit is ms
        """

        if device is None:
            device = adb.device_list()[0]
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
        self.max_width = max_width
        self.bitrate = bitrate
        self.max_fps = max_fps
        self.block_frame = block_frame
        self.stay_awake = stay_awake
        self.lock_screen_orientation = lock_screen_orientation
        self.connection_timeout = connection_timeout

        # Need to destroy
        self.alive = False
        self.__server_stream: Optional[Any] = None
        self.__video_socket: Optional[socket.socket] = None
        self.control_socket: Optional[socket.socket] = None
        self.control_socket_lock = threading.Lock()

    @staticmethod
    def __recv_exact(sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ConnectionError("Socket closed while reading scrcpy metadata")
            data.extend(chunk)
        return bytes(data)

    def __init_server_connection(self) -> None:
        """
        Connect to android server, there will be two sockets, video and control socket.
        This method will set: video_socket, control_socket, resolution variables
        """
        for _ in range(self.connection_timeout // 100):
            try:
                self.__video_socket = self.device.create_connection(
                    Network.LOCAL_ABSTRACT, "scrcpy"
                )
                break
            except AdbError:
                sleep(0.1)
                pass
        else:
            raise ConnectionError("Failed to connect scrcpy-server after 3 seconds")

        dummy_byte = self.__video_socket.recv(1)
        if not len(dummy_byte) or dummy_byte != b"\x00":
            raise ConnectionError("Did not receive Dummy Byte!")

        self.control_socket = self.device.create_connection(
            Network.LOCAL_ABSTRACT, "scrcpy"
        )
        self.device_name = self.__recv_exact(self.__video_socket, 64).decode("utf-8").rstrip("\x00")
        if not len(self.device_name):
            raise ConnectionError("Did not receive Device Name!")

        # scrcpy v3 sends codec id + video width + video height before raw H.264 data.
        _, width, height = struct.unpack(">III", self.__recv_exact(self.__video_socket, 12))
        self.resolution = (width, height)
        self.__video_socket.setblocking(False)

    def __deploy_server(self) -> None:
        """
        Deploy server to android device
        """
        server_root = os.path.abspath(os.path.dirname(__file__))
        server_file_path = server_root + "/scrcpy-server.jar"
        self.device.push(server_file_path, "/data/local/tmp/")
        self.__server_stream = self.device.shell(
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
        self.__server_stream.read(10)

    def __read_server_output(self) -> str:
        if self.__server_stream is None:
            return ""

        conn = getattr(self.__server_stream, "conn", None)
        old_timeout = None
        if conn is not None and hasattr(conn, "gettimeout"):
            old_timeout = conn.gettimeout()
            conn.settimeout(0.2)

        try:
            output = self.__server_stream.read(4096)
        except Exception:
            return ""
        finally:
            if conn is not None and old_timeout is not None:
                conn.settimeout(old_timeout)

        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return str(output)

    def start(self) -> None:
        """
        Start listening video stream
        """
        assert self.alive is False

        self.__deploy_server()
        self.__init_server_connection()
        self.alive = True
        self.__send_to_listeners(EVENT_INIT)
        for frame in self.__stream_loop():
            yield frame

    def stop(self) -> None:
        """
        Stop listening (both threaded and blocked)
        """
        self.alive = False
        if self.__server_stream is not None:
            self.__server_stream.close()
        if self.control_socket is not None:
            self.control_socket.close()
        if self.__video_socket is not None:
            self.__video_socket.close()

    def __stream_loop(self) -> None:
        """
        Core loop for video parsing
        """
        codec = CodecContext.create("h264", "r")
        while self.alive:
            try:
                raw_h264 = self.__video_socket.recv(0x10000)
                if not raw_h264:
                    self.alive = False
                    server_output = self.__read_server_output()
                    message = "Video socket closed; scrcpy-server may have crashed"
                    if server_output:
                        message = f"{message}\n{server_output}"
                    raise ConnectionError(message)
                packets = codec.parse(raw_h264)
                for packet in packets:
                    frames = codec.decode(packet)
                    for frame in frames:
                        frame = frame.to_ndarray(format="bgr24")
                        self.last_frame = frame
                        self.resolution = (frame.shape[1], frame.shape[0])
                        yield frame
            except BlockingIOError:
                time.sleep(0.01)
                if not self.block_frame:
                    yield None
            except OSError as e:  # Socket Closed
                print(e)
                if self.alive:
                    self.alive = False

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

    def __send_to_listeners(self, cls: str, *args, **kwargs) -> None:
        """
        Send event to listeners

        Args:
            cls: Listener type
            *args: Other arguments
            *kwargs: Other arguments
        """
        for fun in self.listeners[cls]:
            fun(*args, **kwargs)

import os
import socket
import struct
import threading
from time import sleep
from typing import Any, Callable, Optional, Union

import cv2
from adbutils import AdbDevice, AdbError, Network, _AdbStreamConnection, adb
from av.codec import CodecContext

from .const import EVENT_FRAME, EVENT_INIT, LOCK_SCREEN_ORIENTATION_UNLOCKED
from .control import ControlSender


class Client:
    def __init__(
        self,
        device: Optional[Union[AdbDevice, str]] = None,
        max_width: int = 0,
        bitrate: int = 8000000,
        max_fps: int = 0,
        flip: bool = False,
        block_frame: bool = False,
        stay_awake: bool = False,
        lock_screen_orientation: int = LOCK_SCREEN_ORIENTATION_UNLOCKED,
    ):
        """
        Create a scrcpy client, this client won't be started until you call the start function
        :param device: Android device, select first one if none, from serial if str
        :param max_width: frame width that will be broadcast from android server
        :param bitrate: bitrate
        :param max_fps: 0 means not limited. supported after android 10
        :param flip: flip the video
        :param block_frame: only return nonempty frames, may block cv2 render thread
        :param stay_awake: keep Android device awake
        :param lock_screen_orientation: lock screen orientation, LOCK_SCREEN_ORIENTATION_*
        """

        if device is None:
            device = adb.device_list()[0]
        elif isinstance(device, str):
            device = adb.device(serial=device)

        self.device = device
        self.listeners = dict(frame=[], init=[])

        # User accessible
        self.last_frame = None
        self.resolution = None
        self.device_name = None
        self.control = ControlSender(self)

        # Params
        self.flip = flip
        self.max_width = max_width
        self.bitrate = bitrate
        self.max_fps = max_fps
        self.block_frame = block_frame
        self.stay_awake = stay_awake
        self.lock_screen_orientation = lock_screen_orientation

        # Need to destroy
        self.alive = False
        self.__server_stream: Optional[_AdbStreamConnection] = None
        self.__video_socket: Optional[socket.socket] = None
        self.__control_socket: Optional[socket.socket] = None
        self.__control_socket_lock = threading.Lock()

    def init_server_connection(self):
        """
        Connect to android server, there will be two sockets, video and control socket.
        This method will set: video_socket, control_socket, resolution variables
        """
        for _ in range(30):
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
        if not len(dummy_byte):
            raise ConnectionError("Did not receive Dummy Byte!")

        self.__control_socket = self.device.create_connection(
            Network.LOCAL_ABSTRACT, "scrcpy"
        )
        self.device_name = self.__video_socket.recv(64).decode("utf-8").rstrip("\x00")
        if not len(self.device_name):
            raise ConnectionError("Did not receive Device Name!")

        res = self.__video_socket.recv(4)
        self.resolution = struct.unpack(">HH", res)
        self.__video_socket.setblocking(False)

    def deploy_server(self):
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
                "1.18",  # Scrcpy server version
                "info",  # Log level: info, verbose...
                f"{self.max_width}",  # Max screen width (long side)
                f"{self.bitrate}",  # Bitrate of video
                f"{self.max_fps}",  # Max frame per second
                f"{self.lock_screen_orientation}",  # Lock screen orientation: LOCK_SCREEN_ORIENTATION
                "true",  # Tunnel forward
                "-",  # Crop screen
                "false",  # Send frame rate to client
                "true",  # Control enabled
                "0",  # Display id
                "false",  # Show touches
                "true" if self.stay_awake else "false",  # Stay awake
                "-",  # Codec (video encoding) options
                "-",  # Encoder name
                "false",  # Power off screen after server closed
            ],
            stream=True,
        )

    def start(self, threaded: bool = False) -> None:
        """
        Start listening video stream
        :param threaded: Run stream loop in a different thread to avoid blocking
        """
        self.deploy_server()
        self.init_server_connection()
        self.alive = True
        self.__send_to_listeners(EVENT_INIT)

        if threaded:
            threading.Thread(target=self.__stream_loop).start()
        else:
            self.__stream_loop()

    def stop(self) -> None:
        """
        Stop listening (both threaded and blocked)
        """
        self.alive = False
        if self.__server_stream is not None:
            self.__server_stream.close()
        if self.__control_socket is not None:
            self.__server_stream.close()
        if self.__video_socket is not None:
            self.__video_socket.close()

    def __stream_loop(self):
        """
        Core loop for video parsing
        """
        codec = CodecContext.create("h264", "r")
        while self.alive:
            try:
                raw_h264 = self.__video_socket.recv(0x10000)
                packets = codec.parse(raw_h264)
                for packet in packets:
                    frames = codec.decode(packet)
                    for frame in frames:
                        frame = frame.to_ndarray(format="bgr24")
                        if self.flip:
                            frame = cv2.flip(frame, 1)
                        self.last_frame = frame
                        self.resolution = (frame.shape[1], frame.shape[0])
                        self.__send_to_listeners(EVENT_FRAME, frame)
            except BlockingIOError:
                if not self.block_frame:
                    self.__send_to_listeners(EVENT_FRAME, None)
            except OSError as e:  # Socket Closed
                if self.alive:
                    raise e

    def add_listener(self, cls: str, listener: Callable[..., Any]) -> None:
        """
        Add a video listener
        :param cls: Listener category, support: init, frame
        :param listener: A function to receive frame np.ndarray
        """
        self.listeners[cls].append(listener)

    def remove_listener(self, cls: str, listener: Callable[..., Any]) -> None:
        """
        Remove a video listener
        :param cls: Listener category, support: init, frame
        :param listener: A function to receive frame np.ndarray
        """
        self.listeners[cls].remove(listener)

    def __send_to_listeners(self, cls: str, *args, **kwargs):
        """
        Send event to listeners
        :param cls: Listener type
        :param *args: Other arguments
        :param *kwargs: Other arguments
        """
        for fun in self.listeners[cls]:
            fun(*args, **kwargs)

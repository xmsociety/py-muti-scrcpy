import functools
import socket
import struct
from time import sleep

import scrcpy
from scrcpy import const


def inject(control_type: int):
    """
    Inject control code, with this inject, we will be able to do unit test

    Args:
        control_type: event to send, TYPE_*
    """

    def wrapper(f):
        @functools.wraps(f)
        def inner(*args, **kwargs):
            package = struct.pack(">B", control_type) + f(*args, **kwargs)
            parent = args[0].parent
            if parent.control_socket is not None:
                try:
                    with parent.control_socket_lock:
                        parent.control_socket.send(package)
                except OSError:
                    parent.alive = False
                    parent.control_socket = None
            return package

        return inner

    return wrapper


class ControlSender:
    def __init__(self, parent):
        self.parent = parent

    @staticmethod
    def _recv_exact(sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ConnectionError("Control socket closed while reading response")
            data.extend(chunk)
        return bytes(data)

    def _require_resolution(self):
        if self.parent.resolution is None:
            raise RuntimeError("Device resolution is not ready; wait until client init")
        return self.parent.resolution

    @inject(const.TYPE_INJECT_KEYCODE)
    def keycode(
        self, keycode: int, action: int = const.ACTION_DOWN, repeat: int = 0
    ) -> bytes:
        """
        Send keycode to device

        Args:
            keycode: const.KEYCODE_*
            action: ACTION_DOWN | ACTION_UP
            repeat: repeat count
        """
        return struct.pack(">Biii", action, keycode, repeat, 0)

    @inject(const.TYPE_INJECT_TEXT)
    def text(self, text: str) -> bytes:
        """
        Send text to device

        Args:
            text: text to send
        """

        buffer = text.encode("utf-8")
        return struct.pack(">i", len(buffer)) + buffer

    @inject(const.TYPE_INJECT_TOUCH_EVENT)
    def touch(
        self, x: int, y: int, action: int = const.ACTION_DOWN, touch_id: int = -1
    ) -> bytes:
        """
        Touch screen

        Args:
            x: horizontal position
            y: vertical position
            action: ACTION_DOWN | ACTION_UP | ACTION_MOVE
            touch_id: Default using virtual id -1, you can specify it to emulate multi finger touch
        """
        x, y = max(x, 0), max(y, 0)
        action_button = 1 if action in (const.ACTION_DOWN, const.ACTION_UP) else 0
        resolution = self._require_resolution()
        return struct.pack(
            ">BqiiHHHii",
            action,
            touch_id,
            int(x),
            int(y),
            int(resolution[0]),
            int(resolution[1]),
            0xFFFF,
            action_button,
            1,
        )

    @inject(const.TYPE_INJECT_SCROLL_EVENT)
    def scroll(self, x: int, y: int, h: int, v: int) -> bytes:
        """
        Scroll screen

        Args:
            x: horizontal position
            y: vertical position
            h: horizontal movement
            v: vertical movement
        """

        x, y = max(x, 0), max(y, 0)
        resolution = self._require_resolution()
        return struct.pack(
            ">iiHHhhi",
            int(x),
            int(y),
            int(resolution[0]),
            int(resolution[1]),
            int(h),
            int(v),
            1,
        )

    @inject(const.TYPE_BACK_OR_SCREEN_ON)
    def back_or_turn_screen_on(self, action: int = const.ACTION_DOWN) -> bytes:
        """
        If the screen is off, it is turned on only on ACTION_DOWN

        Args:
            action: ACTION_DOWN | ACTION_UP
        """
        return struct.pack(">B", action)

    @inject(const.TYPE_EXPAND_NOTIFICATION_PANEL)
    def expand_notification_panel(self) -> bytes:
        """
        Expand notification panel
        """
        return b""

    @inject(const.TYPE_EXPAND_SETTINGS_PANEL)
    def expand_settings_panel(self) -> bytes:
        """
        Expand settings panel
        """
        return b""

    @inject(const.TYPE_COLLAPSE_PANELS)
    def collapse_panels(self) -> bytes:
        """
        Collapse all panels
        """
        return b""

    def get_clipboard(self) -> str:
        """
        Get clipboard
        """
        # Since this function need socket response, we can't auto inject it any more
        s: socket.socket = self.parent.control_socket
        if s is None:
            raise ConnectionError("Control socket is not connected")

        with self.parent.control_socket_lock:
            # Flush socket
            s.setblocking(False)
            for _ in range(16):
                try:
                    s.recv(1024)
                except BlockingIOError:
                    break
            s.setblocking(True)

            # Read package
            package = struct.pack(">BB", const.TYPE_GET_CLIPBOARD, 0)
            s.send(package)
            (code,) = struct.unpack(">B", self._recv_exact(s, 1))
            if code != 0:
                raise RuntimeError(f"Unexpected clipboard response code: {code}")
            (length,) = struct.unpack(">i", self._recv_exact(s, 4))

            return self._recv_exact(s, length).decode("utf-8")

    @inject(const.TYPE_SET_CLIPBOARD)
    def set_clipboard(self, text: str, paste: bool = False) -> bytes:
        """
        Set clipboard

        Args:
            text: the string you want to set
            paste: paste now
        """
        buffer = text.encode("utf-8")
        return struct.pack(">Q?i", 0, paste, len(buffer)) + buffer

    @inject(const.TYPE_SET_SCREEN_POWER_MODE)
    def set_screen_power_mode(self, mode: int = scrcpy.POWER_MODE_NORMAL) -> bytes:
        """
        Set screen power mode

        Args:
            mode: POWER_MODE_OFF | POWER_MODE_NORMAL
        """
        return struct.pack(">?", mode != scrcpy.POWER_MODE_OFF)

    @inject(const.TYPE_ROTATE_DEVICE)
    def rotate_device(self) -> bytes:
        """
        Rotate device
        """
        return b""

    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        move_step_length: int = 5,
        move_steps_delay: float = 0.005,
    ) -> None:
        """
        Swipe on screen

        Args:
            start_x: start horizontal position
            start_y: start vertical position
            end_x: start horizontal position
            end_y: end vertical position
            move_step_length: length per step
            move_steps_delay: sleep seconds after each step
        :return:
        """

        self.touch(start_x, start_y, const.ACTION_DOWN)
        next_x = start_x
        next_y = start_y

        resolution = self._require_resolution()
        if end_x > resolution[0]:
            end_x = resolution[0]

        if end_y > resolution[1]:
            end_y = resolution[1]

        decrease_x = True if start_x > end_x else False
        decrease_y = True if start_y > end_y else False
        while True:
            if decrease_x:
                next_x -= move_step_length
                if next_x < end_x:
                    next_x = end_x
            else:
                next_x += move_step_length
                if next_x > end_x:
                    next_x = end_x

            if decrease_y:
                next_y -= move_step_length
                if next_y < end_y:
                    next_y = end_y
            else:
                next_y += move_step_length
                if next_y > end_y:
                    next_y = end_y

            self.touch(next_x, next_y, const.ACTION_MOVE)

            if next_x == end_x and next_y == end_y:
                self.touch(next_x, next_y, const.ACTION_UP)
                break
            sleep(move_steps_delay)

"""
Copyright (c) 2026 IanVzs. All rights reserved.

Qt -> Android keycode translation, shared by single-device and multi-device
windows so that adding a new mapping only needs touching one place.
"""

import scrcpy

_HARD_CODE = {
    32: scrcpy.KEYCODE_SPACE,
    16777219: scrcpy.KEYCODE_DEL,
    16777248: scrcpy.KEYCODE_SHIFT_LEFT,
    16777220: scrcpy.KEYCODE_ENTER,
    16777217: scrcpy.KEYCODE_TAB,
    16777249: scrcpy.KEYCODE_CTRL_LEFT,
}


def qt_keycode_to_android(code: int) -> int:
    """Translate a Qt key code to the matching Android one, or ``-1``.

    Number keys: Qt 48..57 ('0'..'9') -> Android 7..16 (KEYCODE_0..KEYCODE_9).
    Letters: Qt 65..90 ('A'..'Z') and 97..122 ('a'..'z') -> Android 29..54
    (KEYCODE_A..KEYCODE_Z). The remaining hard mappings live in ``_HARD_CODE``.
    """
    if code == -1:
        return -1
    if 48 <= code <= 57:
        return code - 48 + 7
    if 65 <= code <= 90:
        return code - 65 + 29
    if 97 <= code <= 122:
        return code - 97 + 29
    return _HARD_CODE.get(code, -1)

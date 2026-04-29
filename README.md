# Python MutiScrcpy Client
<p>
    <a href="https://pypi.org/project/muti-scrcpy-client/" target="_blank">
        <img src="https://img.shields.io/pypi/v/muti-scrcpy-client" />
    </a>
    <a href="https://github.com/IanVzs/py-muti-scrcpy/blob/main/.github/workflows/ci.yml" target="_blank">
        <img src="https://img.shields.io/github/workflow/status/ianvzs/py-muti-scrcpy/CI" />
    </a>
    <a href="https://app.codecov.io/gh/ianvzs/py-muti-scrcpy" target="_blank">
        <img src="https://img.shields.io/codecov/c/github/ianvzs/py-muti-scrcpy" />
    </a>
    <img src="https://img.shields.io/github/license/ianvzs/py-muti-scrcpy" />
    <a href="https://pepy.tech/project/muti-scrcpy-client" target="_blank">
        <img src="https://pepy.tech/badge/muti-scrcpy-client" />
    </a>
    <a href="https://github.com/Genymobile/scrcpy/releases/tag/v3.3.4" target="_blank">
        <img src="https://img.shields.io/badge/scrcpy-v3.3.4-violet" />
    </a>
</p>

This package allows you to view and control android device in realtime.

![demo png](https://raw.githubusercontent.com/ianvzs/py-muti-scrcpy/main/demo.png)  

Note: This gif is compressed and experience lower quality than actual.

## How to use
To begin with, you need to install this package via pip:
```shell
pip install "muti-scrcpy-client[ui]"
```
Then, you can start `py-muti-scrcpy` to view the demo:

Note: you can ignore `[ui]` if you don't want to view the demo ui

## Document
Here is the document GitHub page: [Documentation](https://leng-yue.github.io/py-scrcpy-client/)
Also, you can check `scrcpy_ui/main.py` for a full functional demo.

## scrcpy v3.3.4 升级记录

项目内置的 `scrcpy-server.jar` 已从 scrcpy v1.20 升级到 [scrcpy v3.3.4](https://github.com/Genymobile/scrcpy/releases/tag/v3.3.4)，用于适配 Android 16 上 `SurfaceControl.createDisplay`、剪贴板监听等服务端 API 变化。

升级时同步做了这些客户端协议调整：

- 替换 `scrcpy/scrcpy-server.jar` 与 `scrcpy_ui/scrcpy/scrcpy-server.jar` 为官方 `scrcpy-server-v3.3.4`。
- 服务端启动参数从 v1.20 的位置参数改为 v3 的 `key=value` 参数。
- 显式关闭 audio：`audio=false`，保留 video/control 通道，避免旧客户端误读额外音频 socket。
- 保留 codec meta 读取视频宽高，关闭 frame meta，让 Python 解码器继续按裸 H.264 数据解码。
- 更新触摸、滚动、剪贴板、屏幕电源等控制消息格式以匹配 v3 协议。
- 增加视频 socket 关闭时的服务端日志读取，便于定位 Android 端 scrcpy-server 崩溃。
- 修复 Qt 显示非连续 `ndarray` 时的 `ndarray is not C-contiguous` 报错。

如果后续继续跟进 scrcpy 新版本，需要重点检查 `scrcpy/core.py`、`scrcpy/muti_core.py`、`scrcpy/control.py` 和 `scrcpy_ui/scrcpy/` 下的同步实现。

## Reference & Appreciation
- Core: [scrcpy](https://github.com/Genymobile/scrcpy)
- Borther: [py-scrcpy-client](https://github.com/leng-yue/py-scrcpy-client/)
- Idea: [py-android-viewer](https://github.com/razumeiko/py-android-viewer)
- CI: [index.py](https://github.com/index-py/index.py)

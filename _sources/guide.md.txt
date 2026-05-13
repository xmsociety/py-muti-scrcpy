# 使用指南

这篇文档介绍如何在几分钟内运行 Py Muti-Scrcpy，并说明它作为 Python 库、桌面界面和多设备处理示例时分别如何使用。

## 安装

基础库依赖 `adbutils`、`av` 和 `opencv-python`，可以直接安装：

```shell
pip install muti-scrcpy-client
```

如果需要启动自带的 PySide6 桌面界面，请安装 `ui` 可选依赖：

```shell
pip install "muti-scrcpy-client[ui]"
```

项目支持的 Python 版本范围由 `pyproject.toml` 定义：`>=3.10, <3.15`。

## ADB 连接

项目使用 [adbutils](https://github.com/openatx/adbutils) 管理 ADB 连接。Windows 和 macOS 通常可以直接通过 `adbutils` 使用 ADB；Linux 用户一般仍需要先安装系统 ADB，例如 Debian/Ubuntu 可以执行：

```shell
sudo apt install adb
```

知道设备序列号时，可以直接创建客户端：

```python
import scrcpy

client = scrcpy.Client(device="DEVICE_SERIAL")
```

也可以先使用 `adbutils` 获取或连接设备，再把设备对象传给客户端：

```python
import scrcpy
from adbutils import adb

adb.connect("127.0.0.1:5555")
client = scrcpy.Client(device=adb.devices()[0])
```

如果没有传入 `device`，`Client` 会默认使用 ADB 设备列表中的第一个设备。

## 基础客户端

`scrcpy.Client` 会把内置的 `scrcpy-server.jar` 推送到 Android 设备，建立视频 socket 和控制 socket。视频流会被解码成 BGR 格式的 `numpy.ndarray`，因此可以直接交给 OpenCV 处理。

常用初始化参数包括：

- `max_width`：限制服务端输出画面的最长边，`0` 表示不限制。
- `bitrate`：视频码率，默认 `8000000`。
- `max_fps`：最大帧率，`0` 表示不限制；Android 10 之后支持更好。
- `flip`：是否水平翻转画面。
- `block_frame`：是否只发送非空帧；默认非阻塞时可能收到 `None`。
- `stay_awake`：连接期间保持设备唤醒。
- `lock_screen_orientation`：锁定屏幕方向，可使用 `scrcpy.LOCK_SCREEN_ORIENTATION_*` 常量。

## 绑定事件

基础 `Client` 使用事件监听方式分发状态和画面。你可以给同一个事件添加多个监听器。

```python
import cv2
import scrcpy

client = scrcpy.Client(device="DEVICE_SERIAL")


def on_frame(frame):
    # 默认非阻塞模式下，暂时没有新画面时可能收到 None。
    if frame is not None:
        # frame 是 BGR 格式的 numpy.ndarray，符合 OpenCV 默认格式。
        cv2.imshow("device", frame)
    cv2.waitKey(10)


client.add_listener(scrcpy.EVENT_FRAME, on_frame)
client.start()
```

也可以监听初始化事件，读取设备名称、分辨率等信息：

```python
def on_init():
    print(client.device_name)
    print(client.resolution)


client.add_listener(scrcpy.EVENT_INIT, on_init)
```

如果不希望视频循环阻塞主线程，可以使用线程模式启动：

```python
client.start(threaded=True)
```

需要停止连接时调用：

```python
client.stop()
```

## 发送控制操作

客户端会自动创建 `client.control`。它通过 scrcpy 控制通道向设备发送操作，常见能力包括按键、文本、触摸、滑动、滚动、剪贴板、展开/收起面板、旋转设备和控制屏幕电源状态。

触摸示例：

```python
client.control.touch(100, 200, scrcpy.ACTION_DOWN)
client.control.touch(100, 200, scrcpy.ACTION_UP)
```

滑动示例：

```python
client.control.swipe(100, 800, 100, 200)
```

输入文本和按键示例：

```python
client.control.text("hello")
client.control.keycode(scrcpy.KEYCODE_HOME, scrcpy.ACTION_DOWN)
client.control.keycode(scrcpy.KEYCODE_HOME, scrcpy.ACTION_UP)
```

## 获取设备信息

连接建立后可以读取以下属性：

```python
# 当前分辨率，格式为 (width, height)
client.resolution

# 最近一帧画面，类型为 numpy.ndarray 或 None
client.last_frame

# 设备名称
client.device_name
```

## 多设备客户端

`scrcpy.MultiClient` 是面向逐帧消费场景的客户端。它与基础 `Client` 使用同一套 scrcpy 服务端和控制能力，但 `start()` 返回一个生成器，适合在 worker 中循环拉取帧。

> 由于 PyPI 包名 `muti-scrcpy-client` 是历史遗留拼写，该类的旧名 `MutiClient` 仍作为别名保留；新代码请用 `MultiClient`。

```python
import scrcpy

client = scrcpy.MultiClient(device="DEVICE_SERIAL")

for frame in client.start():
    if frame is None:
        continue
    # 在这里处理每一帧图像。
```

需要注意：

- `Client.start(threaded=True)` 是基础客户端的事件循环用法。
- `MultiClient.start()` 是生成器用法，不接收 `threaded` 参数。
- `MultiClient` 默认码率为 `16000000`，适合更高画质的逐帧处理。

## 桌面界面

安装 `ui` 可选依赖后，可以运行入口命令：

```shell
py-muti-scrcpy
```

桌面界面位于 `scrcpy_ui` 包中，主要功能包括：

- 枚举 ADB 设备并在主窗口中显示。
- 勾选一个或多个设备后批量启动或停止。
- 打开单设备画面窗口，实时预览设备屏幕。
- 配合 worker 进程/线程处理多路视频流。
- 启动本地 UDP 服务进程，为后续图像处理或远程服务对接提供示例。

如果只把本项目作为 Python 库使用，可以不安装 PySide6，也不需要启动桌面界面。

## Worker 与 UDP 转发

`workers` 包提供了多设备处理时的辅助组件：

- `ThreadWorker`：线程版 worker，适合在 Qt 单设备窗口中把帧通过信号送回界面，也可以把图像按 UDP 分片发送到服务端。
- `ProcessWorker` 和 `ProcessWorkerManager`：进程版 worker，用于在主界面中管理多设备连接，降低多路视频处理对 UI 线程的影响。
- `UDPServer`：本地 UDP 服务端示例，按自定义包头接收图像分片，解码后返回处理结果结构。
- `schemas` 和 `utils`：定义分包结构、服务端响应结构，以及图像编码/解码工具。

这部分代码更偏向多设备和图像处理流程示例。如果只是控制单台设备，通常直接使用 `scrcpy.Client` 即可。

## 降低 CPU 占用

视频解码是主要的 CPU 消耗来源。自动化脚本通常不需要极高帧率，可以通过以下参数降低压力：

```python
client = scrcpy.Client(
    max_width=720,
    bitrate=2_000_000,
    max_fps=5,
)
```

降低分辨率、码率和帧率后，H.264 解码负载会明显下降，更适合长时间运行的自动化任务。

## 测试与代码检查

仓库中的 `tests` 目录包含 core、control 和进程间通信相关测试。开发时可以结合 `pytest` 运行测试，并使用 `scripts/check.py` 或 `scripts/lint.py` 做格式和静态检查。

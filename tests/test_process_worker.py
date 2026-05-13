"""
Copyright (c) 2026 IanVzs. All rights reserved.

ProcessWorker 的 IPC 拼装测试 —— 不会真正 spawn 子进程或连 ADB，
只验证父端构造的 Pipe / Event / spawn ctx 行为符合预期。
"""

from workers.process_worker import ProcessWorker, ProcessWorkerManager
from workers.schemas import ServerInfo


def _make_worker():
    return ProcessWorker(0, "fake-serial", ServerInfo(host="127.0.0.1", port=9090))


def test_setup_communication_creates_event_and_pipe():
    w = _make_worker()
    assert w.parent_conn is not None
    assert w.child_conn is not None
    assert w.stop_event is not None
    assert w.stop_event.is_set() is False
    assert w._ctx.get_start_method() == "spawn"


def test_setup_communication_resets_state():
    """重建管道时必须给出全新的 Event，不能共享旧对象。"""
    w = _make_worker()
    old_event = w.stop_event
    old_pipe = w.parent_conn

    old_event.set()
    w._setup_communication()

    assert w.stop_event is not old_event
    assert w.stop_event.is_set() is False
    assert w.parent_conn is not old_pipe


def test_get_status_handles_never_started():
    w = _make_worker()
    status = w.get_status()
    assert status["running"] is False
    assert status["alive"] is False
    assert status["last_seen"] is None


def test_manager_handles_unknown_serial_gracefully():
    manager = ProcessWorkerManager()
    # 没有任何 worker 时，stop / status 都应安全返回，不抛异常
    assert manager.stop_worker("nonexistent") is True
    assert manager.get_worker_status("nonexistent") == {
        "running": False,
        "alive": False,
    }
    assert manager.get_all_workers_status() == {}
    manager.stop_all_workers()  # 不抛

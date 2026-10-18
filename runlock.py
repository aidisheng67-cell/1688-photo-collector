"""单实例锁：防止同一台机器同时跑两个 watcher / 控制台。

共享表格的状态列是"协作锁"，但它无法阻止两个进程同时读到同一行。
这个文件锁只解决本机重复启动；跨机器仍应只指定一台服务机。
"""
import ctypes
import os


def _pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        # PROCESS_QUERY_LIMITED_INFORMATION
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class SingleInstance:
    """基于 O_EXCL 创建锁文件；进程退出后留下 pid，可识别并回收僵死锁。"""

    def __init__(self, path="./_pilot_work/collector.lock"):
        self.path = path
        self.fd = None

    def _holder(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0

    def _stale(self):
        pid = self._holder()
        return pid <= 0 or not _pid_alive(pid)

    def acquire(self):
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        for _ in range(2):
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(self.fd, str(os.getpid()).encode("ascii"))
                return True
            except FileExistsError:
                if not self._stale():
                    return False
                try:
                    os.unlink(self.path)
                except OSError:
                    return False
        return False

    def release(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def __enter__(self):
        if not self.acquire():
            pid = self._holder()
            raise RuntimeError(f"已有实例在运行（pid={pid}），锁文件：{self.path}")
        return self

    def __exit__(self, *exc):
        self.release()
        return False

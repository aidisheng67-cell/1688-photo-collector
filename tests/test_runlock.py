from runlock import SingleInstance


def test_second_instance_is_rejected(tmp_path):
    path = str(tmp_path / "collector.lock")
    first = SingleInstance(path)
    second = SingleInstance(path)

    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        first.release()

    assert second.acquire() is True
    second.release()


def test_stale_lock_is_reclaimed(tmp_path):
    path = tmp_path / "collector.lock"
    path.write_text("999999", encoding="utf-8")   # 不存在的 pid
    lock = SingleInstance(str(path))
    assert lock.acquire() is True
    lock.release()


def test_context_manager_raises_for_running_instance(tmp_path):
    path = str(tmp_path / "collector.lock")
    with SingleInstance(path):
        try:
            with SingleInstance(path):
                pass
        except RuntimeError as e:
            assert "已有实例在运行" in str(e)
        else:
            raise AssertionError("expected RuntimeError")

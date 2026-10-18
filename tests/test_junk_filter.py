from PIL import Image

from junk_filter import filter_paths, is_junk


def _img(path, size=(400, 400)):
    Image.new("RGB", size, (120, 120, 120)).save(path)
    return str(path)


def test_normal_image_is_kept(tmp_path):
    assert is_junk(_img(tmp_path / "ok.jpg"))[0] is False


def test_small_image_is_junk(tmp_path):
    junk, reason = is_junk(_img(tmp_path / "small.jpg", (120, 120)))
    assert junk is True
    assert "过小" in reason


def test_wide_banner_is_junk(tmp_path):
    junk, reason = is_junk(_img(tmp_path / "wide.jpg", (1200, 200)))
    assert junk is True
    assert "超宽" in reason


def test_tall_image_is_junk(tmp_path):
    junk, reason = is_junk(_img(tmp_path / "tall.jpg", (200, 1200)))
    assert junk is True
    assert "超高" in reason


def test_unreadable_file_is_junk(tmp_path):
    path = tmp_path / "bad.jpg"
    path.write_bytes(b"not an image")
    junk, reason = is_junk(str(path))
    assert junk is True
    assert "无法打开" in reason


def test_filter_paths_splits_kept_and_dropped(tmp_path):
    ok = _img(tmp_path / "ok.jpg", (400, 400))
    small = _img(tmp_path / "small.jpg", (100, 100))
    kept, dropped = filter_paths([ok, small])
    assert kept == [ok]
    assert dropped[0][0] == small

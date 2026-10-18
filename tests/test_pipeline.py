from pipeline import _unique_dst, safe_id


def test_safe_id_keeps_normal_ids():
    assert safe_id("123456789") == "123456789"
    assert safe_id("A-1_b") == "A-1_b"


def test_safe_id_blocks_path_traversal():
    out = safe_id("../../etc/passwd")
    assert "/" not in out
    assert "\\" not in out
    assert ".." not in out
    assert out


def test_safe_id_empty_falls_back():
    assert safe_id("///") == "id"
    assert safe_id("") == "id"


def test_unique_dst_returns_same_when_free(tmp_path):
    dst = _unique_dst(str(tmp_path), "a.jpg")
    assert dst.endswith("a.jpg")


def test_unique_dst_adds_suffix(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"1")
    (tmp_path / "a_2.jpg").write_bytes(b"2")
    dst = _unique_dst(str(tmp_path), "a.jpg")
    assert dst.endswith("a_3.jpg")

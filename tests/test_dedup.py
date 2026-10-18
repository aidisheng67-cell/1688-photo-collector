import os

from dedup import copy_cached, hamming_hex, lookup


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def all_entries(self):
        return self.rows


def test_hamming_hex():
    assert hamming_hex("0000000000000000", "0000000000000000") == 0
    assert hamming_hex("0000000000000000", "000000000000000f") == 4
    assert hamming_hex("ffffffffffffffff", "0000000000000000") == 64


def test_lookup_returns_closest_within_threshold():
    store = FakeStore([
        ("0000000000000000", "o1", "/tmp/o1", "1,2"),
        ("0000000000000003", "o2", "/tmp/o2", "3"),
        ("ffffffffffffffff", "o3", "/tmp/o3", "4"),
    ])
    hit = lookup(store, "0000000000000001", threshold=2)
    assert hit["src_order"] == "o1"
    assert hit["distance"] == 1


def test_lookup_returns_none_over_threshold():
    store = FakeStore([("ffffffffffffffff", "o1", "/tmp/o1", "1")])
    assert lookup(store, "0000000000000000", threshold=5) is None


def test_lookup_skips_invalid_hex():
    store = FakeStore([("not-hex", "o1", "/tmp/o1", "1")])
    assert lookup(store, "0000000000000000", threshold=5) is None


def test_copy_cached_copies_only_files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.jpg").write_bytes(b"a")
    (src / "b.jpg").write_bytes(b"b")
    (src / "sub").mkdir()
    dst = tmp_path / "dst"

    assert copy_cached(str(src), str(dst)) == 2
    assert sorted(os.listdir(dst)) == ["a.jpg", "b.jpg"]

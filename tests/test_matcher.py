import numpy as np
from PIL import Image

from matcher import decide, hamming, orb_inliers, phash_bits

CFG = {
    "match_high": 5,
    "match_review": 10,
    "orb_high": 20,
    "orb_weak": 10,
    "orb_nfeatures": 1000,
    "orb_ratio": 0.8,
}


def _noise(path, seed=0, size=(240, 240)):
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr).save(path)
    return str(path)


def test_phash_identical_and_different(tmp_path):
    a = _noise(tmp_path / "a.png", seed=1)
    b = _noise(tmp_path / "b.png", seed=1)
    c = _noise(tmp_path / "c.png", seed=2)

    pa, pb, pc = phash_bits(a), phash_bits(b), phash_bits(c)

    assert hamming(pa, pb) == 0
    assert hamming(pa, pc) > 0


def test_orb_identical_has_inliers(tmp_path):
    a = _noise(tmp_path / "a.png", seed=3)
    assert orb_inliers(a, a) > 0


def test_decide_three_levels():
    assert decide(3, 0, CFG) == "HIT"       # pHash 命中
    assert decide(5, 0, CFG) == "HIT"       # 边界值命中
    assert decide(7, 0, CFG) == "REVIEW"    # pHash 落复核区
    assert decide(20, 20, CFG) == "HIT"     # ORB 命中
    assert decide(20, 10, CFG) == "REVIEW"  # ORB 落复核区
    assert decide(20, 0, CFG) == "NONE"

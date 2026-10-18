from learn import Learner


def test_stats_and_threshold_suggestion(tmp_path):
    learner = Learner(str(tmp_path / "learn.sqlite"), min_samples=5, margin=4, floor=20)
    for i in range(4):
        learner.record(f"o{i}", f"g{i}", phash=8, orb=12, label="ok")
    learner.record("bad1", "g9", phash=6, orb=18, label="bad")
    learner.record("bad2", "g10", phash=7, orb=21, label="bad")

    stats = learner.stats()
    assert stats["总数"] == 6
    assert stats["对"] == 4
    assert stats["误配"] == 2

    # max(bad orb)=21 + margin 4 = 25
    assert learner.suggest_orb_high(20) == 25
    learner.close()


def test_no_suggestion_without_enough_samples(tmp_path):
    learner = Learner(str(tmp_path / "learn.sqlite"), min_samples=20)
    learner.record("o1", "g1", phash=5, orb=30, label="bad")
    assert learner.suggest_orb_high(20) is None
    learner.close()


def test_no_suggestion_without_bad_cases(tmp_path):
    learner = Learner(str(tmp_path / "learn.sqlite"), min_samples=3)
    for i in range(3):
        learner.record(f"o{i}", f"g{i}", phash=5, orb=30, label="ok")
    assert learner.suggest_orb_high(20) is None
    learner.close()


def test_export_csv(tmp_path):
    learner = Learner(str(tmp_path / "learn.sqlite"))
    learner.record("o1", "g1", phash=5, orb=20, label="ok")
    out = tmp_path / "out.csv"
    assert learner.export_csv(str(out)) == 1
    text = out.read_text(encoding="utf-8-sig")
    assert "order_id,offer_id,phash,orb,label" in text
    learner.close()

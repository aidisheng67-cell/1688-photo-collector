import json

from obs import Obs


def test_order_log_is_redacted(tmp_path):
    obs = Obs(str(tmp_path / "logs"))
    obs.order({
        "order_id": "1001",
        "decision": "ERROR",
        "error": "request failed: https://api/x?key=abc123&secret=def456",
        "note": {"token": "xyz789"},
    })

    line = next(iter(open(obs.jsonl, encoding="utf-8")))
    record = json.loads(line)
    text = json.dumps(record, ensure_ascii=False)

    assert "abc123" not in text
    assert "def456" not in text
    assert "xyz789" not in text
    assert "key=***" in text
    assert "secret=***" in text
    assert record["order_id"] == "1001"


def test_report_aggregates(tmp_path):
    obs = Obs(str(tmp_path / "logs"))
    obs.order({"order_id": "1", "decision": "DONE", "saved_images": 3})
    obs.order({"order_id": "2", "decision": "DONE", "dedup": True, "saved_images": 0})
    obs.order({"order_id": "3", "decision": "REVIEW"})
    agg = obs.report()
    assert agg["总数"] == 3
    assert agg["已完成(含去重复用)"] == 2
    assert agg["其中去重复用"] == 1
    assert agg["待复核"] == 1
    assert agg["采集图片总数"] == 3

"""
obs.py —— 结构化日志（JSONL）+ 批次报告（§5.7 / §12.13）。
每订单一条 jsonl，机器可读、Claude Code 可直接解析定位；批次报告人看 md / 机器读 json。
日志不写密钥。
"""
import os
import json
import time

from config import SECRET_KEYS, redact_text


def _clean(value, key=None):
    # 按字段名兜底：token/app_secret 等即使只以独立值出现也脱敏
    if key is not None and str(key).lower() in SECRET_KEYS and value not in (None, ""):
        return "***"
    if isinstance(value, dict):
        return {k: _clean(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class Obs:
    def __init__(self, log_dir="./日志"):
        self.run_dir = os.path.join(log_dir, "run_" + time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(self.run_dir, exist_ok=True)
        self.jsonl = os.path.join(self.run_dir, "orders.jsonl")
        self.records = []

    def order(self, record):
        """record: dict，至少含 order_id/decision/error 等。追加一行 jsonl。"""
        record = _clean(dict(record))
        record.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
        self.records.append(record)
        with open(self.jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def report(self):
        rs = self.records
        agg = {
            "总数": len(rs),
            "已完成(含去重复用)": sum(1 for r in rs if r.get("decision") == "DONE"),
            "其中去重复用": sum(1 for r in rs if r.get("dedup")),
            "待复核": sum(1 for r in rs if r.get("decision") == "REVIEW"),
            "无匹配": sum(1 for r in rs if r.get("decision") == "NONE"),
            "错误": sum(1 for r in rs if r.get("decision") == "ERROR"),
            "采集图片总数": sum(int(r.get("saved_images") or 0) for r in rs),
        }
        with open(os.path.join(self.run_dir, "report.json"), "w", encoding="utf-8") as f:
            json.dump(agg, f, ensure_ascii=False, indent=2)
        with open(os.path.join(self.run_dir, "report.md"), "w", encoding="utf-8") as f:
            f.write("# 批次报告\n\n")
            for k, v in agg.items():
                f.write(f"- {k}: {v}\n")
        return agg

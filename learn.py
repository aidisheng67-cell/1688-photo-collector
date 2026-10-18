"""
learn.py —— 复核结果标定库 + 保守自动学习 + 全量导出（§2 决策）。
每条复核判定(分数 pHash/ORB + 人工标签 对/错)入库;据此保守调阈值:
  - 安全方向(把出过误配的分数区移出自动通过)自动执行;
  - 放宽(减少复核)只在"历史0误配 + 样本足 + 留余量"时;
  - 永远可导出全部记录,供人工/更强特征分析。
"""
import os
import csv
import time
import sqlite3


class Learner:
    def __init__(self, path="./缓存/learn.sqlite", min_samples=20, margin=4, floor=20):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS reviews(
            ts REAL, order_id TEXT, offer_id TEXT, phash INTEGER, orb INTEGER, label TEXT)""")
        self.db.commit()
        self.min_samples = min_samples
        self.margin = margin
        self.floor = floor

    def record(self, order_id, offer_id, phash, orb, label):
        """label: 'ok'(真同图) / 'bad'(不同品=有害误配)。"""
        self.db.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                        (time.time(), order_id, offer_id,
                         int(phash) if phash is not None else None,
                         int(orb) if orb is not None else None, label))
        self.db.commit()

    def all(self):
        return self.db.execute(
            "SELECT order_id,offer_id,phash,orb,label FROM reviews").fetchall()

    def stats(self):
        rows = self.all()
        return {"总数": len(rows),
                "对": sum(1 for r in rows if r[4] == "ok"),
                "误配": sum(1 for r in rows if r[4] == "bad")}

    def export_csv(self, path):
        rows = self.all()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["order_id", "offer_id", "phash", "orb", "label"])
            w.writerows(rows)
        return len(rows)

    def suggest_orb_high(self, cur_orb_high):
        """
        保守建议 orb_high:取"能把所有已知误配排除"的最低阈值 + 安全余量。
        = max(误配的ORB) + margin。数据不足则不动(返回 None)。
        既能在误配都偏低时放宽(减少复核)、又始终把已知误配挡在外面。
        """
        rows = [r for r in self.all() if r[3] is not None]
        if len(rows) < self.min_samples:
            return None
        bad_orbs = [r[3] for r in rows if r[4] == "bad"]
        if not bad_orbs:
            return None        # 没出过误配,不轻易放宽,保持现状
        new = max(bad_orbs) + self.margin
        new = max(self.floor, new)
        return new if new != cur_orb_high else None

    def close(self):
        self.db.close()

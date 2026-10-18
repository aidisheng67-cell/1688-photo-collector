"""store.py —— 缓存持久化（sqlite）。款缓存：以客户图指纹为 key，记录已采过的那套图位置。"""
import os
import sqlite3
import time


class Store:
    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS dedup(
            phash TEXT PRIMARY KEY,
            src_order TEXT,
            image_dir TEXT,
            offer_ids TEXT,
            created_at REAL)""")
        self.db.commit()

    def all_entries(self):
        return self.db.execute(
            "SELECT phash, src_order, image_dir, offer_ids FROM dedup").fetchall()

    def add(self, phash, src_order, image_dir, offer_ids):
        self.db.execute("INSERT OR REPLACE INTO dedup VALUES(?,?,?,?,?)",
                        (phash, src_order, image_dir, ",".join(offer_ids), time.time()))
        self.db.commit()

    def delete_by_names(self, names):
        """按订单文件夹名(= src_order 或 image_dir 末段)删除缓存条目。返回删除数。"""
        names = set(names)
        if not names:
            return 0
        rows = self.db.execute("SELECT phash, src_order, image_dir FROM dedup").fetchall()
        to_del = [ph for ph, src, img in rows
                  if (src in names) or (os.path.basename((img or "").rstrip("/\\")) in names)]
        for ph in to_del:
            self.db.execute("DELETE FROM dedup WHERE phash=?", (ph,))
        self.db.commit()
        return len(to_del)

    def close(self):
        self.db.close()

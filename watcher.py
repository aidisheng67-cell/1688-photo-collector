"""
watcher.py —— 共享表格监听（自动触发）。
确认列打勾 -> 去抖 confirm_delay_seconds(默认180=3分钟,控制台可调) -> 自动处理 -> 回写状态。
集成：去重缓存(§5.6)、垃圾图过滤(§5.3)、三档含复核(§5.2)、结构化日志(§12.13)、健壮性(§9)。
状态列即锁；多机协作建议仅一台"服务机"跑本监听。
"""
import os
import json
import time

import matcher
import pipeline
from api_client import ThirdPartyApi
from config import load_config
from runlock import SingleInstance
from sheets import make_backend
from store import Store
from obs import Obs

PEND, PROC, DONE, REVIEW, NONE, ERR = "待处理", "处理中", "已完成", "待复核", "无匹配", "错误"
SKIP = {DONE, REVIEW, NONE, ERR}            # 终态：跳过（待复核=等人工）
_MAP = {"DONE": DONE, "REVIEW": REVIEW, "NONE": NONE}


def _is_quota(e):
    s = str(e)
    return any(k in s for k in ("超量", "超过", "次数", "配额", "余额", "quota", "limit", "4001", "4003", "4005"))


def _is_transient(e):
    s = str(e)
    return any(k in s for k in ("5000", "data error", "timeout", "Timeout", "Connection",
                                "timed out", "ReadTimeout", "Max retries"))


def _now():
    return time.time()


def _ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Watcher:
    def __init__(self, cfg, dry_run=None, reporter=None, learner=None):
        self.cfg = cfg
        self.reporter = reporter      # callable(event:dict) 给控制台报进度/日志
        self.learner = learner        # 保守自动学习:据复核标定自动调 orb_high
        scfg = cfg["sheet"]
        self.backend = make_backend(scfg, cfg["paths"].get("work", "./_pilot_work"))
        self.poll = scfg.get("poll_seconds", 30)
        self.delay = scfg.get("confirm_delay_seconds", 180)
        self.stale = scfg.get("stale_minutes", 30) * 60
        self.dry_run = scfg.get("dry_run", False) if dry_run is None else dry_run
        paths = cfg["paths"]
        self.out_root = paths.get("output", "./输出")
        self.work = paths.get("work", "./_pilot_work")
        self.review_dir = paths.get("review", "./复核")
        self.mcfg = cfg["matcher"]
        self.dedup_th = cfg.get("thresholds", {}).get("dedup", 5)
        self.img_dedup = cfg.get("thresholds", {}).get("img_dedup", 5)
        self.junk_cfg = cfg.get("junk_filter", {})
        os.makedirs(self.work, exist_ok=True)
        self.api = None if self.dry_run else ThirdPartyApi(cfg["api"], work_dir=self.work)
        self.store = None if self.dry_run else Store(paths.get("cache", "./缓存/cache.sqlite"))
        self.obs = Obs(paths.get("log", "./日志"))
        self.state_path = os.path.join(self.work, "watch_state.json")
        self.state = self._load_state()

    def _load_state(self):
        try:
            return json.load(open(self.state_path, encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self):
        json.dump(self.state, open(self.state_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    def _report(self, ev):
        if self.reporter:
            try:
                self.reporter(ev)
            except Exception:
                pass

    def _apply_learn(self):
        """保守自动学习:据复核标定建议的 orb_high(若有)自动应用。"""
        if not self.learner:
            return
        new = self.learner.suggest_orb_high(self.mcfg.get("orb_high", 24))
        if new and new != self.mcfg.get("orb_high"):
            old = self.mcfg.get("orb_high")
            self.mcfg["orb_high"] = new
            self._report({"type": "learn", "msg": f"自动学习:orb_high {old} → {new}"})

    def _process(self, row):
        oid, url = row["id"], row["image_url"]
        out_root = self.cfg["paths"].get("output", self.out_root)   # 实时读,设置即时生效
        self.backend.write_back(row["_rownum"], {"status": PROC, "time": _ts()})
        self.state.setdefault(oid, {})["proc_at"] = _now()
        if self.dry_run:
            res = {"status": "DONE", "dedup": False, "sellers": "(dry)", "saved_images": 0, "save_path": "(dry-run)"}
        else:
            col = self.cfg.get("collect", {})   # 实时读,控制台改"采集卖家数量"下一轮即生效
            res = pipeline.process_order(
                self.api, matcher, self.mcfg, oid, url, out_root,
                {"max_per": int(col.get("max_sellers", 6)),
                 "max_scan": int(col.get("max_scan", 25)),
                 "max_detail": int(col.get("max_detail", 30)),
                 "rerun_extra": int(col.get("rerun_extra", 3))},
                work=self.work, store=self.store, dedup_threshold=self.dedup_th,
                junk_cfg=self.junk_cfg, review_dir=self.review_dir, img_dedup=self.img_dedup)
        st = _MAP.get(res["status"], NONE)
        self.backend.write_back(row["_rownum"], {
            "status": st, "save_path": res.get("save_path", ""), "time": _ts()})
        self.obs.order({"order_id": oid, "decision": res["status"], "dedup": res.get("dedup"),
                        "sellers": res.get("sellers"), "saved_images": res.get("saved_images")})
        self.state.pop(oid, None)
        print(f"  [{oid}] 完成: {st} 卖家={res.get('sellers')} 图={res.get('saved_images')}"
              f"{' (去重复用)' if res.get('dedup') else ''}")
        self._report({"type": "order", "order_id": oid, "status": st,
                      "sellers": res.get("sellers"), "images": res.get("saved_images"),
                      "dedup": res.get("dedup")})

    def tick(self):
        self._apply_learn()
        delay = self.cfg["sheet"].get("confirm_delay_seconds", self.delay)        # 实时读
        stale = self.cfg["sheet"].get("stale_minutes", self.stale // 60) * 60     # 实时读
        rows = self.backend.read_rows()
        processed = 0
        for row in rows:
            oid, url, confirmed, status = row["id"], row["image_url"], row["confirm"], row["status"]
            if not oid or not url:
                continue
            # 僵死锁回收：处理中且超过 stale 视为崩溃残留，重新处理
            if status == PROC:
                st = self.state.get(oid, {})
                if not (st.get("proc_at") and _now() - st["proc_at"] > stale):
                    continue
                print(f"  [{oid}] 处理中僵死锁超时，回收重处理")
            elif status in SKIP:
                self.state.pop(oid, None)
                continue
            else:  # 空 / 待处理
                if not confirmed:
                    self.state.pop(oid, None)
                    continue
                st = self.state.setdefault(oid, {})
                st.setdefault("confirmed_at", _now())
                waited = _now() - st["confirmed_at"]
                if waited < delay:
                    print(f"  [{oid}] 已确认，去抖中，还差 {int(delay - waited)}s")
                    continue
            # 触发处理
            print(f"  [{oid}] -> 开始处理")
            try:
                self._process(row)
                processed += 1
            except Exception as e:
                if _is_quota(e):
                    print(f"  [{oid}] 配额耗尽，暂停本轮（该行留待处理，下次再跑）: {e!r}")
                    self.backend.write_back(row["_rownum"], {"status": PEND, "time": _ts()})
                    self.state.pop(oid, None)
                    break          # 停止本轮，避免继续撞配额
                if _is_transient(e):
                    print(f"  [{oid}] 瞬时错误，留待重试: {e!r}")
                    self.backend.write_back(row["_rownum"], {"status": PEND, "time": _ts()})
                    self.state.pop(oid, None)
                    continue
                print(f"  [{oid}] 真错误，标记错误: {e!r}")
                self.obs.order({"order_id": oid, "decision": "ERROR", "error": str(e)})
                self.backend.write_back(row["_rownum"], {"status": ERR, "time": _ts()})
                self.state.pop(oid, None)
        self._save_state()
        if processed:
            self.obs.report()
        return processed

    def run_forever(self):
        print(f"监听启动：每 {self.poll}s 查表，确认后去抖 {self.delay}s 再处理"
              f"{'（DRY-RUN）' if self.dry_run else ''}")
        while True:
            try:
                self.tick()
            except Exception as e:
                print("本轮异常:", repr(e))
            time.sleep(self.poll)

    def run_loop(self, stop_event):
        """供控制台用:可被 stop_event 停止的监听循环(线程里跑)。"""
        self._report({"type": "status", "running": True})
        while not stop_event.is_set():
            try:
                self.tick()
                self._report({"type": "tick", "at": _ts()})
            except Exception as e:
                self._report({"type": "monitor_error", "msg": f"本轮异常: {e!r}"})
            # 可中断的等待(轮询间隔实时读,设置即时生效)
            poll = int(self.cfg["sheet"].get("poll_seconds", self.poll))
            for _ in range(max(1, poll)):
                if stop_event.is_set():
                    break
                time.sleep(1)
        self._report({"type": "status", "running": False})


if __name__ == "__main__":
    cfg = load_config()
    lock_path = os.path.join(cfg.get("paths", {}).get("work", "./_pilot_work"), "collector.lock")
    with SingleInstance(lock_path):
        Watcher(cfg).run_forever()

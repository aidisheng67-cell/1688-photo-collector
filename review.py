"""
review.py —— 复核流程(整合进控制台用)。
list_pending(): 列出待复核记录(来自 复核/{id}.json,内含客户图+top候选+各候选分数)。
submit(): 人选中"真同图"后 -> 自动采集选中商品详情图到 输出/{id}/ -> 记录学习标签 ->
          回写表格状态 -> 删除该复核记录。全程不用再点第二次。
"""
import os
import json
import glob
import time
import shutil

import requests

import junk_filter
from pipeline import safe_id, _unique_dst


def list_pending(review_dir):
    out = []
    for p in sorted(glob.glob(os.path.join(review_dir, "*.json"))):
        try:
            out.append(json.load(open(p, encoding="utf-8")))
        except Exception:
            pass
    return out


def _dl(url, dst, retries=3):
    """带 UA + 重试退避(与 pipeline._dl 一致),治 CDN 偶发限流。"""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            with open(dst, "wb") as f:
                f.write(r.content)
            return dst
        except Exception as e:
            last = e
            time.sleep(0.4 * (attempt + 1))
    raise last if last else RuntimeError("download failed")


def submit(api, cfg, learner, backend, rec, chosen_offer_ids):
    """
    rec: 复核记录; chosen_offer_ids: 人判为真同图的 offer 列表(可空=全否决)。
    返回 {status, saved_images}。
    """
    oid = rec["order_id"]
    sid = safe_id(oid)                                  # 路径安全名
    out_root = cfg["paths"].get("output", "./输出")
    save_dir = os.path.join(out_root, sid)
    os.makedirs(save_dir, exist_ok=True)
    tmp = os.path.join(cfg["paths"].get("work", "./_pilot_work"), "_review", sid)
    os.makedirs(tmp, exist_ok=True)
    chosen = set(chosen_offer_ids or [])

    # 1) 记录学习标签(展示过的候选:选中=对,未选=误配)
    if learner is not None:
        for c in rec.get("candidates", []):
            label = "ok" if c["offer_id"] in chosen else "bad"
            learner.record(oid, c["offer_id"], c.get("phash"), c.get("orb"), label)

    # 2) 采集选中商品:先下临时目录,过滤垃圾图后移入 save_dir。
    #    不做跨卖家去重(与主管道一致);防重名、不覆盖任何已有图。
    total = 0
    for off in chosen:
        try:
            imgs = api.all_images(off)        # 详情图 + 买家秀(有则采、无则跳)
        except Exception:
            continue
        dl = []
        for k, u in enumerate(imgs[:30]):
            ext = ".png" if u.lower().split("?")[0].endswith(".png") else ".jpg"
            try:
                dl.append(_dl(u, os.path.join(tmp, f"{off}_detail_{k+1:02d}{ext}")))
            except Exception:
                pass
        kept, dropped = junk_filter.filter_paths(dl, cfg.get("junk_filter"))
        for p, _r in dropped:
            try:
                os.remove(p)
            except Exception:
                pass
        for p in kept:
            dst = _unique_dst(save_dir, os.path.basename(p))
            try:
                shutil.move(p, dst)
                total += 1
            except Exception:
                pass

    status = "已完成" if chosen else "无匹配"

    # 3) 回写表格(按 id 在当前表里找到该行)
    if backend is not None:
        try:
            for row in backend.read_rows():
                if row["id"] == oid:
                    backend.write_back(row["_rownum"], {
                        "status": status,
                        "save_path": save_dir if chosen else "",
                        "time": time.strftime("%Y-%m-%d %H:%M:%S")})
                    break
        except Exception:
            pass

    # 4) 删除复核记录
    try:
        os.remove(os.path.join(cfg["paths"].get("review", "./复核"), f"{sid}.json"))
    except Exception:
        pass

    return {"status": status, "saved_images": total}

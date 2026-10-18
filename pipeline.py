"""
pipeline.py —— 单订单处理：(订单id, 客户图URL) -> [去重缓存] -> 拍立淘 -> 同图判定(三档)
  -> [垃圾图过滤] -> 存详情图到 输出/{id}/。客户图是公网URL，拍立淘直接用，无需 upload。

三档（§5.2）：
  - 有 HIT(同图卖家) -> DONE，逐个采集（垃圾图过滤后保存）。
  - 无 HIT 但有 REVIEW(边界) -> REVIEW，写复核记录(top候选)，交人工，绝不自动通过。
  - 都没有 -> NONE。
去重（§5.6）：处理前用客户图指纹查缓存，命中即把缓存那套图【复制】进本 id 文件夹，跳过接口。
"""
import os
import re
import json
import time
import shutil
import requests

import dedup as dedup_mod
import junk_filter


def safe_id(oid):
    """把订单 id 规整成文件系统安全的名字(防 / \\ .. : 等穿越/非法字符)。数字 id 不变。"""
    s = re.sub(r"[^0-9A-Za-z_\-]", "_", str(oid)).strip("._")
    return s or "id"


def _unique_dst(save_dir, name):
    """返回 save_dir 下不与现有文件重名的路径(重跑时避免覆盖旧图)。"""
    dst = os.path.join(save_dir, name)
    if not os.path.exists(dst):
        return dst
    base, ext = os.path.splitext(name)
    i = 2
    while os.path.exists(os.path.join(save_dir, f"{base}_{i}{ext}")):
        i += 1
    return os.path.join(save_dir, f"{base}_{i}{ext}")

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
       "Referer": "https://www.1688.com/"}


def _dl(url, dst, retries=3):
    """带 UA 头 + 失败重试退避，治 alicdn 等 CDN 的限流/拒连。"""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_UA, timeout=30)
            r.raise_for_status()
            with open(dst, "wb") as f:
                f.write(r.content)
            return dst
        except Exception as e:
            last = e
            time.sleep(0.4 * (attempt + 1))
    raise last if last else RuntimeError("download failed")


def process_order(api, matcher, mcfg, order_id, image_url, out_root, opts,
                  work="./_pilot_work", store=None, dedup_threshold=5,
                  junk_cfg=None, review_dir="./复核", img_dedup=5):
    """返回结果 dict：status(DONE/REVIEW/NONE) + 明细。每个 id 都建独立 输出/{id}/。"""
    os.makedirs(work, exist_ok=True)
    sid = safe_id(order_id)                    # 路径一律用安全名(数字 id 不变)
    tmp = os.path.join(work, "_orders", sid)
    os.makedirs(tmp, exist_ok=True)
    save_dir = os.path.join(out_root, sid)
    is_rerun = os.path.isdir(save_dir)        # 该 id 之前已处理过 = "再次上传" → 重采、不走缓存

    cust = _dl(image_url, os.path.join(tmp, "customer.jpg"))

    max_per = opts.get("max_per", 6)
    max_scan = opts.get("max_scan", 25)
    max_detail = opts.get("max_detail", 30)
    existing_hashes = []      # 仅"文件夹已有旧图"的指纹(重跑只增不删用);不做跨卖家去重
    if is_rerun:
        # 再次上传:① 不走缓存,重新搜款;② 扩大同图卖家数(默认 +3);
        #           ③ 只增不删:旧图全部保留,新图仅补充"文件夹里还没有的"
        max_per += opts.get("rerun_extra", 3)
        max_scan = max(max_scan, max_per * 6, 40)
        try:  # 先把已有旧图的指纹装进 existing_hashes,后面与旧图相同的新图就不重复保存
            for fn in os.listdir(save_dir):
                fpth = os.path.join(save_dir, fn)
                if not os.path.isfile(fpth):
                    continue
                try:
                    h = dedup_mod.fingerprint(fpth)
                    if h:
                        existing_hashes.append(h)
                except Exception:
                    pass
        except Exception:
            pass

    # ---- 去重前置（§5.6）：仅对"新 id"复用缓存;同一 id 再次上传不走缓存、重新搜 ----
    try:
        fp = dedup_mod.fingerprint(cust)
    except Exception:
        fp = None
    if store is not None and not is_rerun and fp:
        hit = dedup_mod.lookup(store, fp, dedup_threshold)
        if hit:
            n = dedup_mod.copy_cached(hit["image_dir"], save_dir)
            return {"status": "DONE", "dedup": True, "sellers": len(hit["offer_ids"].split(",")) if hit["offer_ids"] else 0,
                    "saved_images": n, "save_path": save_dir, "src_order": hit["src_order"]}

    cands, _method = api.search_by_image_robust(image_url)
    # 按销量从高到低排(接口若无销量字段则全为0,sorted 稳定→保持原顺序);从销量最高的开始采
    cands = sorted(cands, key=lambda c: c.get("sales_num", 0), reverse=True)
    offer_ids, review_cands = [], []
    total_saved = 0
    for c in cands[:max_scan]:
        if len(offer_ids) >= max_per:
            break
        off = c["offer_id"]
        local = []
        for j, u in enumerate(c.get("image_urls", [])[:3]):
            try:
                local.append(_dl(u, os.path.join(tmp, f"{off}_{j}.jpg")))
            except Exception:
                pass
        if not local:
            continue
        try:
            bp, bo = matcher.best_match(cust, local, mcfg)
        except Exception:
            continue
        d = matcher.decide(bp, bo, mcfg)
        if d == "REVIEW" and len(review_cands) < 3:
            review_cands.append({"offer_id": off, "title": c.get("title", ""),
                                 "image_url": c.get("main_image", ""), "phash": bp, "orb": bo})
            continue
        if d != "HIT":
            continue
        # ---- 命中即采集该卖家详情图:先下到临时目录,过滤+去重后,
        #      只把"文件夹里还没有的新图"移入 save_dir(旧图绝不删改)----
        offer_ids.append(off)
        try:
            imgs = api.all_images(off)        # 详情图 + 买家秀(有则采、无则跳)
        except Exception:
            imgs = []
        dl_paths = []
        for k, u in enumerate(imgs[:max_detail]):
            try:
                ext = ".png" if u.lower().split("?")[0].endswith(".png") else ".jpg"
                dl_paths.append(_dl(u, os.path.join(tmp, f"{off}_detail_{k+1:02d}{ext}")))
            except Exception:
                pass
        kept, dropped = junk_filter.filter_paths(dl_paths, junk_cfg)
        for p, _reason in dropped:                       # 垃圾图删除(临时目录里)
            try:
                os.remove(p)
            except Exception:
                pass
        os.makedirs(save_dir, exist_ok=True)
        # 不做跨卖家去重:命中卖家的图(过垃圾过滤后)全部保存。
        # 仅重跑时与"文件夹已有旧图"去重(只增不删);旧图绝不删改。
        for p in kept:
            if existing_hashes:
                try:
                    h = dedup_mod.fingerprint(p)
                except Exception:
                    h = None
                if h and any(dedup_mod.hamming_hex(h, s) <= img_dedup for s in existing_hashes):
                    try:
                        os.remove(p)                      # 与文件夹已有旧图相同 -> 不重复保存
                    except Exception:
                        pass
                    continue
            dst = _unique_dst(save_dir, os.path.basename(p))
            try:
                shutil.move(p, dst)                       # 移入,防重名、不覆盖任何旧文件
            except Exception:
                continue
            total_saved += 1

    if offer_ids:
        if store is not None and fp:
            try:
                store.add(fp, order_id, save_dir, offer_ids)
            except Exception:
                pass
        return {"status": "DONE", "dedup": False, "sellers": len(offer_ids),
                "saved_images": total_saved, "save_path": save_dir}

    # ---- 边界 -> 复核（不自动通过）----
    if review_cands:
        os.makedirs(review_dir, exist_ok=True)
        rec = {"order_id": order_id, "customer_image": image_url, "candidates": review_cands}
        json.dump(rec, open(os.path.join(review_dir, f"{sid}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        return {"status": "REVIEW", "dedup": False, "sellers": 0,
                "saved_images": 0, "save_path": "", "review_candidates": len(review_cands)}

    # ---- 无同图：建空文件夹（每个 id 都有自己的文件夹），直接下一个 ----
    os.makedirs(save_dir, exist_ok=True)
    return {"status": "NONE", "dedup": False, "sellers": 0, "saved_images": 0, "save_path": save_dir}

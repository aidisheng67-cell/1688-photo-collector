"""
dedup.py —— 款缓存 + 近重复查找（§5.6）。
要点：去重只省"重复的活"（接口调用+下载），**不省文件夹**。
每个订单 id 永远有自己独立的 输出/{id}/；命中重复时把缓存里那套图【复制】进新 id 文件夹。
key = 客户图 pHash 指纹；只有"确实同一张图"(汉明距离 <= dedup 阈值)才复用——保守、不会错并。
"""
import os
import shutil

import matcher


def fingerprint(path):
    """客户图 pHash -> 16位十六进制字符串（64bit）。"""
    bits = matcher.phash_bits(path)
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return f"{v:016x}"


def _hamming_hex(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def hamming_hex(a, b):
    """两个指纹十六进制串的汉明距离（跨卖家去重等场景用）。"""
    return _hamming_hex(a, b)


def lookup(store, fp_hex, threshold):
    """在缓存里找与 fp_hex 汉明距离 <= threshold 的条目；命中返回该条目，否则 None。"""
    best = None
    best_d = threshold + 1
    for phash, src, image_dir, offers in store.all_entries():
        try:
            d = _hamming_hex(phash, fp_hex)
        except ValueError:
            continue
        if d <= threshold and d < best_d:
            best_d = d
            best = {"phash": phash, "src_order": src,
                    "image_dir": image_dir, "offer_ids": offers, "distance": d}
    return best


def copy_cached(image_dir, dst_dir):
    """把缓存目录里的图复制进新 id 的文件夹。返回复制张数。"""
    os.makedirs(dst_dir, exist_ok=True)
    n = 0
    if not (image_dir and os.path.isdir(image_dir)):
        return 0
    for fn in os.listdir(image_dir):
        sp = os.path.join(image_dir, fn)
        if os.path.isfile(sp):
            shutil.copy2(sp, os.path.join(dst_dir, fn))
            n += 1
    return n

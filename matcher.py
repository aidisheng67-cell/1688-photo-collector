"""
matcher.py —— 同图判定核心（pHash + ORB）。
【阶段0测试与后续生产共用；参数为试点实测的参考值（见主文档 §15），需用真实数据继续标定。】

两步法：
  1) pHash（DCT 感知哈希）：抓「原样搬图 / 缩放 / 轻度压缩」——快、准。
  2) ORB 关键点匹配：抓「裁剪 / 换背景 / 换色 / 拼图」——pHash 失效时的兜底，抗裁剪。
依赖：Pillow, numpy, opencv-python(-headless)
"""
import numpy as np
import cv2
from PIL import Image
try:
    import pillow_avif  # noqa: F401  注册 AVIF 解码,使 PIL 能直接打开 .avif(360buyimg 等)
except Exception:
    pass


def _to_gray(path, cap=1400, clahe=True):
    """读图转灰度，限制最长边，做 CLAHE 对比度均衡（提升 ORB 在改图上的稳健性）。"""
    arr = np.array(Image.open(path).convert("RGB"))
    g = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    s = cap / max(h, w)
    if s < 1:
        g = cv2.resize(g, (int(w * s), int(h * s)))
    if clahe:
        g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
    return g


def phash_bits(path, hash_size=8):
    """DCT 版 pHash，返回 64 位布尔指纹。"""
    img = Image.open(path).convert("L").resize((32, 32))
    a = np.float32(np.array(img))
    d = cv2.dct(a)
    block = d[:hash_size, :hash_size]
    med = np.median(block.flatten()[1:])   # 去掉 DC 分量后取中位数
    return (block > med).flatten()


def hamming(a, b):
    return int(np.count_nonzero(a != b))


def orb_inliers(path1, path2, nfeatures=4000, ratio=0.8):
    """ORB + 比值测试 + RANSAC，返回内点数（越大越可能是同一张图的局部）。"""
    g1, g2 = _to_gray(path1), _to_gray(path2)
    orb = cv2.ORB_create(nfeatures=nfeatures, fastThreshold=5,
                         scaleFactor=1.2, nlevels=12)
    k1, d1 = orb.detectAndCompute(g1, None)
    k2, d2 = orb.detectAndCompute(g2, None)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return 0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    good = []
    for mn in bf.knnMatch(d1, d2, k=2):
        if len(mn) == 2 and mn[0].distance < ratio * mn[1].distance:
            good.append(mn[0])
    if len(good) < 4:
        return 0
    src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    return int(mask.sum()) if mask is not None else 0


def best_match(customer_path, candidate_paths, cfg):
    """
    把客户图与「一个候选商品的若干张图」逐一比对，返回该候选的最佳成绩：
      (最小 pHash 距离, 最大 ORB 内点数)
    仅当 pHash 没命中时才跑 ORB（省算力）。
    """
    cph = phash_bits(customer_path)
    best_p, best_o = 64, 0
    for p in candidate_paths:
        try:
            best_p = min(best_p, hamming(cph, phash_bits(p)))
            if best_p > cfg["match_high"]:
                best_o = max(best_o, orb_inliers(
                    customer_path, p, cfg["orb_nfeatures"], cfg["orb_ratio"]))
        except Exception:
            continue   # 单张图坏掉不影响整体
    return best_p, best_o


def decide(best_p, best_o, cfg):
    """三档判定：HIT(自动) / REVIEW(复核) / NONE(无匹配)。"""
    if best_p <= cfg["match_high"] or best_o >= cfg["orb_high"]:
        return "HIT"
    if (cfg["match_high"] < best_p <= cfg["match_review"]) or \
       (cfg["orb_weak"] <= best_o < cfg["orb_high"]):
        return "REVIEW"
    return "NONE"

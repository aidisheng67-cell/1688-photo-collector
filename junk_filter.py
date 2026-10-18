"""
junk_filter.py —— 垃圾图过滤（§5.3 / §12.5）。
第1层·几何规则（免费、最快）：丢极端长条 banner、过小 logo/图标。
注意：尺码表是"文字/表格类图"，但尺寸/长宽比通常正常，第1层几何规则**不会**误删它；
      真正区分"尺码表 vs 文字海报"需第2层 OCR（PaddleOCR，重、暂缓，见 §12.5 第3层多模态同）。
对外：filter_paths(paths) -> (kept_paths, dropped[(path,reason)])
"""
from PIL import Image


def is_junk(path, min_long_side=300, max_aspect=3.0, max_aspect_tall=4.0):
    try:
        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        return True, "无法打开"
    if max(w, h) < min_long_side:
        return True, f"过小({w}x{h}) 疑似logo/图标"
    if h > 0 and w / h > max_aspect:
        return True, f"超宽({w}x{h}) 疑似banner"
    if w > 0 and h / w > max_aspect_tall:
        return True, f"超高({w}x{h}) 疑似长条"
    return False, ""


def filter_paths(paths, cfg=None):
    cfg = cfg or {}
    kept, dropped = [], []
    for p in paths:
        junk, reason = is_junk(
            p,
            cfg.get("min_long_side", 300),
            cfg.get("max_aspect", 3.0),
            cfg.get("max_aspect_tall", 4.0),
        )
        (dropped if junk else kept).append((p, reason) if junk else p)
    return kept, dropped

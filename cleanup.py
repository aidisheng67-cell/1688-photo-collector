"""
cleanup.py —— 清理旧的输出订单文件夹。
按"创建时间早于 keep_days 天"识别 输出/{id}/ 子文件夹,交人工确认后删除。
"""
import os
import time
import shutil


def find_old_dirs(out_root, keep_days):
    """返回 out_root 下【创建时间早于 keep_days 天】的子文件夹信息(按最旧在前)。"""
    now = time.time()
    cutoff = now - float(keep_days) * 86400
    res = []
    if not os.path.isdir(out_root):
        return res
    for name in os.listdir(out_root):
        p = os.path.join(out_root, name)
        if not os.path.isdir(p):
            continue
        try:
            ct = os.path.getctime(p)          # Windows 上为创建时间
        except Exception:
            continue
        if ct < cutoff:
            res.append({"name": name, "path": p, "ctime": ct,
                        "age_days": int((now - ct) / 86400),
                        "created": time.strftime("%Y-%m-%d", time.localtime(ct))})
    res.sort(key=lambda x: x["ctime"])
    return res


def delete_dirs(dirs):
    """删除给定文件夹列表,返回 (成功数, [(名称, 错误)...])。"""
    ok, fail = 0, []
    for d in dirs:
        try:
            shutil.rmtree(d["path"])
            ok += 1
        except Exception as e:
            fail.append((d["name"], str(e)))
    return ok, fail

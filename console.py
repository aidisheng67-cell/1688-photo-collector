"""
console.py —— 实拍图采集 · 桌面控制台(customtkinter,侧边栏仪表盘·高级深色风)。
左侧导航(监控台/待复核/设置) + 右侧内容区。功能:监听开关、今日统计、实时日志、
复核(图上点选→提交即采)、设置、导出、托盘常驻、界面状态记忆。
启动: python console.py
"""
import os
import sys
import io
import json
import time
import queue
import shutil
import threading

from tkinter import messagebox, filedialog, BooleanVar
import customtkinter as ctk

import matcher
import pipeline
import cleanup
import review as review_mod
from learn import Learner
from api_client import ThirdPartyApi
from config import load_config, save_config
from runlock import SingleInstance
from watcher import Watcher

try:
    import requests
    from PIL import Image
    _IMG_OK = True
    try:
        import pillow_avif  # noqa: F401  注册 AVIF 解码
    except Exception:
        pass
except Exception:
    _IMG_OK = False

try:
    import pystray
    from PIL import Image as _PILImage
    _TRAY_OK = True
except Exception:
    _TRAY_OK = False

CONFIG = "config.yaml"
STATE_FILE = "ui_state.json"
# —— 配色(浅色 · 干净专业·靛蓝强调) ——
BG_WINDOW = "#F4F5F7"   # 窗口底(比卡片深一档,让白卡片浮起)
BG_BAND = "#FAFBFC"     # 顶栏 / 参数带底
BG_PANEL = "#FFFFFF"    # 大面板 / Tab 内容
BG_CARD = "#FFFFFF"     # 卡片 / 输入框
BG_HOVER = "#F2F4F7"    # hover 极淡灰
LINE_HAIR = "#ECEDF0"   # 发丝边线(默认卡片)
LINE_SOFT = "#E1E4E8"   # 弱边线(输入框/幽灵按钮)
INK = "#1F2430"         # 主文字(深蓝灰,非纯黑)
SUBINK = "#5A6473"      # 次文字
MUTED = "#98A0AE"       # 弱文字 / 单位 / 时间戳
ACCENT = "#3E63DD"      # 强调:主按钮 / Tab 选中 / 聚焦
ACCENT_HOVER = "#3358D4"
ON_ACCENT = "#FFFFFF"
OK_C, WARN_C, ERR_C = "#2F9E68", "#E0921A", "#E5484D"
LOGBG = "#FBFCFD"       # 日志区(略沉的白,减刺眼)
LOGINK = "#3A4250"      # 日志文字
SEG_BG = "#ECEEF1"      # 分段控件底
# —— 兼容旧弹窗类引用 ——
BG_APP, LINE = BG_WINDOW, LINE_HAIR
PAGE, CARD, HOVER = BG_PANEL, BG_CARD, BG_HOVER
ACCENT_PRESS = ACCENT_HOVER
PRIM, PRIM_HOVER = ACCENT, ACCENT_HOVER
FONT = "Microsoft YaHei UI"

# —— 中英文文案表 ——
LANG = {
    "zh": {
        "brand": "实拍图采集 · 监控控制台", "params": "运行参数",
        "params_hint": "修改保存后于下个轮询周期生效",
        "p_debounce": "去抖(秒)", "p_poll": "轮询(秒)", "p_sellers": "采集卖家(个)",
        "p_outdir": "输出文件夹", "pick_dir": "选择文件夹",
        "tab_dash": "监控台", "tab_review": "待复核",
        "m_total": "本次已处理", "m_done": "已完成", "m_none": "无匹配",
        "m_review": "待复核", "m_err": "出错", "m_images": "采集图片",
        "log_title": "实时日志",
        "b_check": "立即检查一次", "b_run": "跑单个订单", "b_ip": "显示出口IP",
        "b_clean": "清理旧输出", "b_exp_rev": "导出复核记录", "b_exp_diag": "导出诊断",
        "b_settings": "设置", "b_refresh": "刷新",
        "review_hint": "点每条右侧『复核』→ 勾选与客户图同款的卖家 → 提交,机器自动采集所选商品图。",
        "review_empty": "暂无待复核订单", "review_order": "订单", "review_cands": "个候选", "review_btn": "复核",
        "st_running": "监听中", "st_stopped": "已停止", "st_error": "异常",
        "btn_start": "▶ 开始监听", "btn_stop": "■ 停止监听", "lang_btn": "EN",
        "d_cancel": "取消", "d_close": "关闭", "d_ok": "确认", "tip": "提示",
        "stop_title": "停止监听", "stop_ok": "停止监听",
        "stop_msg": "监听正在运行中。\n本次已处理 {t} 单 · 完成 {d} · 待复核 {r} · 出错 {e}\n\n停止后将不再自动查表和采集。确定停止监听吗?",
        "run_title": "跑单个订单", "run_desc": "手动处理一条:填订单 id 与客户图 URL,机器立即搜款采集。",
        "run_id": "订单 id", "run_url": "客户图 URL", "run_run": "运行",
        "run_ph_id": "如 6541231551", "run_need": "请填写订单 id 和客户图 URL",
        "run_cfm_title": "运行单个订单", "run_cfm_ok": "确认运行",
        "run_cfm_msg": "将立即处理这一单:\n订单 id:{oid}\n客户图:{url}\n\n机器会去搜同款并采集商品图。确定运行吗?",
        "run_cfm_parallel": "\n(监听正在运行,本次为手动补跑,与监听并行、互不影响)",
        "clean_title": "清理旧输出",
        "clean_desc": "删除输出文件夹中『创建时间早于设定天数』的订单文件夹,用于释放空间。删除不可恢复,请先扫描确认。",
        "clean_days_lbl": "删除几天前的文件夹:", "clean_scan": "扫描",
        "clean_hint": "点『扫描』先看有哪些会被删除。",
        "clean_none": "没有创建于 {days} 天前的输出文件夹。",
        "clean_row": "{name}   （{created} 创建 · {age} 天前）",
        "clean_found": "扫描到 {n} 个可删除文件夹（早于 {days} 天）。",
        "clean_del": "确定删除", "clean_need_days": "请填写一个非负整数天数",
        "clean_cfm_title": "确认删除旧输出", "clean_cfm_ok": "永久删除",
        "clean_cfm_msg": "将永久删除 {n} 个输出文件夹（创建于 {days} 天前）。\n删除后无法恢复,确定吗?",
        "clean_done_title": "清理完成", "clean_done_msg": "已删除 {ok} 个文件夹。",
        "clean_done_fail": "\n{n} 个删除失败(可能被占用)。",
        "set_title": "设置", "set_save": "保存", "set_pickdir": "选择文件夹",
        "set_hint": "输出/去抖/轮询 保存即时生效;切后端或凭证需停止再开始监听。",
        "set_cfm_title": "保存设置", "set_cfm_ok": "确认保存",
        "set_cfm_msg": "即将把当前设置写入 config.yaml,覆盖原有配置。",
        "set_cfm_running": "\n\n监听正在运行中:输出/去抖/轮询保存后即时生效;切换表格后端或凭证需停止再重新开始监听才生效。",
        "set_saved_title": "已保存", "set_saved_msg": "设置已写入 config.yaml",
        "f_api_key": "onebound key", "f_api_secret": "onebound secret",
        "f_debounce": "去抖秒数(180=3分钟)", "f_poll": "轮询秒数", "f_sellers": "采集卖家数量(个)",
        "f_keepdays": "输出保留天数(清理旧输出用)", "f_backend": "表格后端(dingtalk/xlsx)",
        "f_dt_appkey": "钉钉 AppKey", "f_dt_appsecret": "钉钉 AppSecret",
        "f_dt_workbook": "在线表格 workbookId", "f_dt_sheet": "工作表 sheetId",
        "f_dt_operator": "操作人 unionId", "f_output": "输出文件夹",
        "rev_title": "复核 · 订单 {id}",
        "rev_instr": "勾选与客户图『同一张图 / 同一产品』的卖家;提交后机器自动采集所选商品详情图。",
        "rev_customer": "客户图", "rev_same": "同图",
        "rev_submit": "提交(自动采集所选)", "rev_reject": "全部否决(无匹配)",
        "img_loading": "(图加载中)", "img_none": "(无图)", "img_fail": "(图加载失败)",
    },
    "en": {
        "brand": "Sourcing Photos · Monitor Console", "params": "Run parameters",
        "params_hint": "Saved changes apply on the next poll cycle",
        "p_debounce": "Debounce (s)", "p_poll": "Poll (s)", "p_sellers": "Sellers",
        "p_outdir": "Output folder", "pick_dir": "Choose folder",
        "tab_dash": "Dashboard", "tab_review": "Review",
        "m_total": "Processed", "m_done": "Done", "m_none": "No match",
        "m_review": "To review", "m_err": "Errors", "m_images": "Images",
        "log_title": "Live log",
        "b_check": "Check now", "b_run": "Run one order", "b_ip": "Show egress IP",
        "b_clean": "Clean old output", "b_exp_rev": "Export reviews", "b_exp_diag": "Export diagnostics",
        "b_settings": "Settings", "b_refresh": "Refresh",
        "review_hint": "Click 'Review' on a row, tick sellers matching the customer image, submit; images are collected automatically.",
        "review_empty": "No orders to review", "review_order": "Order", "review_cands": " candidates", "review_btn": "Review",
        "st_running": "Monitoring", "st_stopped": "Stopped", "st_error": "Error",
        "btn_start": "▶ Start", "btn_stop": "■ Stop", "lang_btn": "中",
        "d_cancel": "Cancel", "d_close": "Close", "d_ok": "Confirm", "tip": "Notice",
        "stop_title": "Stop monitoring", "stop_ok": "Stop",
        "stop_msg": "Monitoring is running.\nProcessed {t} · done {d} · to review {r} · errors {e}\n\nStopping halts auto polling and collection. Stop monitoring?",
        "run_title": "Run one order", "run_desc": "Process one manually: enter order id and customer image URL; the tool searches and collects immediately.",
        "run_id": "Order id", "run_url": "Customer image URL", "run_run": "Run",
        "run_ph_id": "e.g. 6541231551", "run_need": "Please enter order id and customer image URL",
        "run_cfm_title": "Run one order", "run_cfm_ok": "Run",
        "run_cfm_msg": "About to process this order:\nOrder id: {oid}\nImage: {url}\n\nThe tool will search for matches and collect images. Run?",
        "run_cfm_parallel": "\n(Monitoring is running; this manual run works in parallel.)",
        "clean_title": "Clean old output",
        "clean_desc": "Delete order folders in the output directory created earlier than the set number of days, to free space. Deletion is irreversible; scan first.",
        "clean_days_lbl": "Delete folders older than (days):", "clean_scan": "Scan",
        "clean_hint": "Click 'Scan' to preview what will be deleted.",
        "clean_none": "No output folders created earlier than {days} days ago.",
        "clean_row": "{name}   (created {created} · {age} days ago)",
        "clean_found": "Found {n} folders to delete (older than {days} days).",
        "clean_del": "Delete", "clean_need_days": "Please enter a non-negative integer number of days",
        "clean_cfm_title": "Confirm deletion", "clean_cfm_ok": "Delete permanently",
        "clean_cfm_msg": "Permanently delete {n} output folders (created {days}+ days ago).\nThis cannot be undone. Continue?",
        "clean_done_title": "Cleanup done", "clean_done_msg": "Deleted {ok} folders.",
        "clean_done_fail": "\n{n} failed (possibly in use).",
        "set_title": "Settings", "set_save": "Save", "set_pickdir": "Choose folder",
        "set_hint": "Output/debounce/poll apply immediately; changing backend or credentials needs a monitor restart.",
        "set_cfm_title": "Save settings", "set_cfm_ok": "Save",
        "set_cfm_msg": "Settings will be written to config.yaml, overwriting the current config.",
        "set_cfm_running": "\n\nMonitoring is running: output/debounce/poll apply immediately; switching backend or credentials needs a monitor restart.",
        "set_saved_title": "Saved", "set_saved_msg": "Settings written to config.yaml",
        "f_api_key": "onebound key", "f_api_secret": "onebound secret",
        "f_debounce": "Debounce seconds (180 = 3 min)", "f_poll": "Poll seconds", "f_sellers": "Sellers to collect",
        "f_keepdays": "Output retention days (for cleanup)", "f_backend": "Sheet backend (dingtalk/xlsx)",
        "f_dt_appkey": "DingTalk AppKey", "f_dt_appsecret": "DingTalk AppSecret",
        "f_dt_workbook": "Workbook ID", "f_dt_sheet": "Sheet ID",
        "f_dt_operator": "Operator unionId", "f_output": "Output folder",
        "rev_title": "Review · Order {id}",
        "rev_instr": "Tick sellers with the same image / same product as the customer image; selected product images are collected automatically on submit.",
        "rev_customer": "Customer image", "rev_same": "Same",
        "rev_submit": "Submit (collect selected)", "rev_reject": "Reject all (no match)",
        "img_loading": "(loading)", "img_none": "(no image)", "img_fail": "(load failed)",
    },
}


def app_dir():
    return os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))


def ghost(parent, text, cmd, width=116):
    return ctk.CTkButton(parent, text=text, command=cmd, width=width, height=32, corner_radius=6,
                         fg_color="transparent", text_color=SUBINK, border_color=LINE_SOFT, border_width=1,
                         hover_color=BG_HOVER, font=ctk.CTkFont(FONT, 13))


class ConfirmDialog:
    """工业风二次确认弹框,模态,返回 self.result (True/False)。"""
    def __init__(self, app, title, message, ok_text=None, ok_color=ACCENT,
                 ok_ink=ON_ACCENT, ok_hover=ACCENT_HOVER):
        self.result = False
        ok_text = ok_text or app.T("d_ok")
        w = ctk.CTkToplevel(app.root)
        w.title(title)
        w.configure(fg_color=BG_WINDOW)
        w.resizable(False, False)
        w.transient(app.root)
        self.w = w
        card = ctk.CTkFrame(w, fg_color=BG_PANEL, corner_radius=8, border_width=1, border_color=LINE_HAIR)
        card.pack(fill="both", expand=True, padx=16, pady=16)
        ctk.CTkLabel(card, text="⚠  " + title, font=app.f_h1, text_color=INK).pack(anchor="w", padx=22, pady=(20, 6))
        ctk.CTkLabel(card, text=message, font=app.f_n, text_color=SUBINK, justify="left",
                     wraplength=380, anchor="w").pack(anchor="w", padx=22, pady=(0, 8))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(side="bottom", anchor="e", padx=22, pady=(6, 18))
        ghost(row, app.T("d_cancel"), self._cancel, 100).pack(side="left", padx=(0, 10))
        ctk.CTkButton(row, text=ok_text, command=self._ok, width=132, height=36, corner_radius=6,
                      fg_color=ok_color, hover_color=ok_hover, text_color=ok_ink, font=app.f_n).pack(side="left")
        w.update_idletasks()
        ww, hh = 460, max(230, card.winfo_reqheight() + 32)
        x = app.root.winfo_x() + (app.root.winfo_width() - ww) // 2
        y = app.root.winfo_y() + (app.root.winfo_height() - hh) // 2
        w.geometry(f"{ww}x{hh}+{max(x, 0)}+{max(y, 0)}")
        w.protocol("WM_DELETE_WINDOW", self._cancel)
        w.grab_set()
        w.focus()
        app.root.wait_window(w)

    def _ok(self):
        self.result = True
        self.w.destroy()

    def _cancel(self):
        self.result = False
        self.w.destroy()


def ask_confirm(app, title, message, ok_text=None, ok_color=ACCENT,
                ok_ink=ON_ACCENT, ok_hover=ACCENT_HOVER):
    return ConfirmDialog(app, title, message, ok_text, ok_color, ok_ink, ok_hover).result


class App:
    def __init__(self, root):
        self.root = root
        ctk.set_appearance_mode("light")
        root.title("实拍图采集 · 控制台")
        root.minsize(1080, 700)
        root.configure(fg_color=BG_WINDOW)
        self.cfg = load_config(CONFIG)
        self.q = queue.Queue()
        self.stop_event = None
        self.thread = None
        self.tray = None
        self.learner = Learner("./缓存/learn.sqlite")
        try:
            self.api = ThirdPartyApi(self.cfg["api"], work_dir=self.cfg["paths"].get("work", "./_pilot_work"))
        except Exception:
            self.api = None
        self.stats = {"total": 0, "done": 0, "none": 0, "review": 0, "err": 0, "images": 0}
        self.running = False
        self.ui_state = self._load_ui_state()
        root.geometry(self.ui_state.get("geometry") or "1200x780")
        self._save_ticks = 0
        self.lang = self.ui_state.get("lang", "zh")
        self._status_mode = "stopped"
        self._i18n = []          # [(widget, key)] 切换语言时重贴文字
        self.f_h1 = ctk.CTkFont(FONT, 16, "bold")     # 品牌 / 弹窗标题
        self.f_sec = ctk.CTkFont(FONT, 13, "bold")    # 分区标题 / Tab
        self.f_big = ctk.CTkFont("Segoe UI", 26, "bold")   # 大数字(适中)
        self.f_param = ctk.CTkFont("Segoe UI", 16, "bold") # 参数输入
        self.f_btn = ctk.CTkFont(FONT, 13, "bold")    # 主开关
        self.f_n = ctk.CTkFont(FONT, 13)
        self.f_lbl = ctk.CTkFont(FONT, 12)
        self.f_s = ctk.CTkFont(FONT, 11)
        self.f_log = ctk.CTkFont("Consolas", 12)
        self._build()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(400, self._drain)

    # ---------- 布局 ----------
    def _build(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(2, weight=1)     # Tab 区可伸展
        self._build_header()      # row 0
        self._build_params()      # row 1
        self._build_body()        # row 2
        self._build_statusbar()   # row 3

    def T(self, key):
        d = LANG.get(self.lang) or LANG["zh"]
        return d.get(key) or LANG["zh"].get(key, key)

    def _reg(self, widget, key):
        self._i18n.append((widget, key))
        return widget

    def _build_header(self):
        hdr = ctk.CTkFrame(self.root, fg_color=BG_BAND, corner_radius=0, height=56)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        ctk.CTkFrame(hdr, fg_color=LINE_HAIR, height=1).place(relx=0, rely=1.0, relwidth=1, anchor="sw")
        brand = ctk.CTkFrame(hdr, fg_color="transparent")
        brand.pack(side="left", padx=16)
        ctk.CTkLabel(brand, text="◆", font=self.f_h1, text_color=ACCENT).pack(side="left")
        self._reg(ctk.CTkLabel(brand, text="  " + self.T("brand"), font=self.f_h1, text_color=INK),
                  "brand").pack(side="left")
        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.pack(side="right", padx=16)
        self.lang_btn = ctk.CTkButton(right, text=self.T("lang_btn"), command=self._toggle_lang,
                                      width=52, height=28, corner_radius=6, fg_color="transparent",
                                      border_width=1, border_color=LINE_SOFT, text_color=SUBINK,
                                      hover_color=BG_HOVER, font=ctk.CTkFont(FONT, 12))
        self.lang_btn.pack(side="right", padx=(12, 0))
        self.btn_toggle = ctk.CTkButton(right, text=self.T("btn_start"), command=self.toggle, width=132, height=34,
                                        corner_radius=6, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                        text_color=ON_ACCENT, font=self.f_btn)
        self.btn_toggle.pack(side="right", padx=(12, 0))
        self.side_status = ctk.CTkLabel(right, text="  ● " + self.T("st_stopped") + "  ",
                                        font=ctk.CTkFont(FONT, 11, "bold"), text_color="#5A6473",
                                        fg_color="#F0F1F3", corner_radius=11, height=22)
        self.side_status.pack(side="right")

    def _build_params(self):
        band = ctk.CTkFrame(self.root, fg_color=BG_BAND, corner_radius=0, height=96)
        band.grid(row=1, column=0, sticky="ew")
        band.grid_propagate(False)
        ctk.CTkFrame(band, fg_color=LINE_HAIR, height=1).place(relx=0, rely=1.0, relwidth=1, anchor="sw")
        inner = ctk.CTkFrame(band, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=(8, 10))
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        self._reg(ctk.CTkLabel(top, text=self.T("params"), font=self.f_sec, text_color=INK), "params").pack(side="left")
        self._reg(ctk.CTkLabel(top, text=self.T("params_hint"), font=self.f_s, text_color=MUTED),
                  "params_hint").pack(side="right")
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        s = self.cfg.get("sheet", {})
        col = self.cfg.get("collect", {})
        self.e_debounce = self._param_int(row, "p_debounce", "sheet.confirm_delay_seconds", s.get("confirm_delay_seconds", 180))
        self.e_poll = self._param_int(row, "p_poll", "sheet.poll_seconds", s.get("poll_seconds", 30))
        self.e_sellers = self._param_int(row, "p_sellers", "collect.max_sellers", col.get("max_sellers", 6))
        of = ctk.CTkFrame(row, fg_color="transparent")
        of.pack(side="left", fill="x", expand=True)
        self._reg(ctk.CTkLabel(of, text=self.T("p_outdir"), font=self.f_lbl, text_color=SUBINK), "p_outdir").pack(anchor="w")
        of_row = ctk.CTkFrame(of, fg_color="transparent")
        of_row.pack(fill="x", pady=(3, 0))
        field = ctk.CTkFrame(of_row, fg_color=BG_CARD, corner_radius=6, border_width=1, border_color=LINE_SOFT, height=30)
        field.pack(side="left", fill="x", expand=True, padx=(0, 8))
        field.pack_propagate(False)
        self.lbl_outdir = ctk.CTkLabel(field, text=self._short_path(self.cfg["paths"].get("output", "./输出")),
                                       font=self.f_n, text_color=SUBINK, anchor="w")
        self.lbl_outdir.pack(side="left", fill="x", expand=True, padx=10)
        self._reg(ghost(of_row, self.T("pick_dir"), self._pick_outdir, 96), "pick_dir").pack(side="left")

    def _param_int(self, parent, label_key, cfg_path, default):
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.pack(side="left", padx=(0, 14))
        self._reg(ctk.CTkLabel(cell, text=self.T(label_key), font=self.f_lbl, text_color=SUBINK), label_key).pack(anchor="w")
        e = ctk.CTkEntry(cell, width=88, height=30, corner_radius=6, fg_color=BG_CARD, border_width=1,
                         border_color=LINE_SOFT, font=self.f_param, text_color=INK, justify="center")
        e.pack(pady=(3, 0))
        e.insert(0, str(default))
        e.bind("<Return>", lambda ev: self._apply_param_int(cfg_path, e))
        e.bind("<FocusOut>", lambda ev: self._apply_param_int(cfg_path, e))
        return e

    def _build_body(self):
        wrap = ctk.CTkFrame(self.root, fg_color="transparent")
        wrap.grid(row=2, column=0, sticky="nsew", padx=16, pady=(12, 8))
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(1, weight=1)
        seg = ctk.CTkFrame(wrap, fg_color=SEG_BG, corner_radius=8)
        seg.grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.tab_btns = {}
        for key, tkey in [("dash", "tab_dash"), ("review", "tab_review")]:
            b = ctk.CTkButton(seg, text=self.T(tkey), width=112, height=30, corner_radius=6,
                              fg_color="transparent", text_color="#7A8394", hover_color=BG_HOVER,
                              font=self.f_sec, command=lambda k=key: self._show_tab(k))
            b.pack(side="left", padx=3, pady=3)
            self.tab_btns[key] = self._reg(b, tkey)
        body = ctk.CTkFrame(wrap, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.page_dash = ctk.CTkFrame(body, fg_color="transparent")
        self.page_review = ctk.CTkFrame(body, fg_color="transparent")
        self.page_dash.grid(row=0, column=0, sticky="nsew")
        self.page_review.grid(row=0, column=0, sticky="nsew")
        self._build_dashboard(self.page_dash)
        self._build_review(self.page_review)
        self._show_tab("dash")

    def _show_tab(self, key):
        (self.page_dash if key == "dash" else self.page_review).tkraise()
        for k, b in self.tab_btns.items():
            if k == key:
                b.configure(fg_color=BG_PANEL, text_color=INK)
            else:
                b.configure(fg_color="transparent", text_color="#7A8394")
        if key == "review":
            self.refresh_reviews()

    def _toggle_lang(self):
        self.lang = "en" if self.lang == "zh" else "zh"
        self._apply_lang()
        self._save_ui_state()

    def _apply_lang(self):
        for w, key in self._i18n:
            try:
                w.configure(text=self.T(key))
            except Exception:
                pass
        self.lang_btn.configure(text=self.T("lang_btn"))
        self._set_toggle(self.running)
        self._set_status(self._status_mode)
        self.lbl_info.configure(text=self._cadence_text())
        self.refresh_reviews()

    def _build_dashboard(self, p):
        p.grid_columnconfigure(0, weight=36, uniform="c")
        p.grid_columnconfigure(1, weight=64, uniform="c")
        p.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(p, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ctk.CTkFrame(p, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        met = ctk.CTkFrame(left, fg_color="transparent")
        met.pack(fill="x")
        self.metric_lbls = {}
        cards = [("total", "m_total", LINE_HAIR), ("done", "m_done", OK_C), ("none", "m_none", LINE_HAIR),
                 ("review", "m_review", WARN_C), ("err", "m_err", ERR_C), ("images", "m_images", ACCENT)]
        for i, (key, nkey, strip) in enumerate(cards):
            met.grid_columnconfigure(i % 2, weight=1, uniform="m")
            self.metric_lbls[key] = self._metric(met, nkey, strip, i // 2, i % 2)

        # 次级操作:横跨整屏底部一整行(避免挤在窄列里被裁掉)
        acts = ctk.CTkFrame(p, fg_color="transparent")
        acts.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for key, cmd in [("b_check", self.check_now), ("b_run", self.run_single), ("b_ip", self.show_egress_ip),
                         ("b_clean", self.open_cleanup), ("b_exp_rev", self.export_reviews),
                         ("b_exp_diag", self.export_diag), ("b_settings", self.open_settings)]:
            self._reg(ghost(acts, self.T(key), cmd, 108), key).pack(side="left", padx=(0, 6))

        logwrap = ctk.CTkFrame(right, fg_color=BG_PANEL, corner_radius=8, border_width=1, border_color=LINE_HAIR)
        logwrap.pack(fill="both", expand=True)
        self._reg(ctk.CTkLabel(logwrap, text=self.T("log_title"), font=self.f_sec, text_color=SUBINK),
                  "log_title").pack(anchor="w", padx=14, pady=(10, 0))
        self.log = ctk.CTkTextbox(logwrap, font=self.f_log, fg_color=LOGBG, text_color=LOGINK,
                                  corner_radius=8, border_width=0)
        self.log.pack(fill="both", expand=True, padx=12, pady=10)
        self.log.configure(state="disabled")

    def _metric(self, parent, name_key, strip, r, c):
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=8, border_width=1, border_color=LINE_HAIR)
        card.grid(row=r, column=c, padx=4, pady=4, sticky="ew")
        ctk.CTkFrame(card, fg_color=strip, width=3, corner_radius=0).pack(side="left", fill="y")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(side="left", fill="both", expand=True, padx=14, pady=12)
        self._reg(ctk.CTkLabel(inner, text=self.T(name_key), font=self.f_lbl, text_color=SUBINK), name_key).pack(anchor="w")
        v = ctk.CTkLabel(inner, text="0", font=self.f_big, text_color=INK)
        v.pack(anchor="w")
        return v

    def _build_review(self, p):
        head = ctk.CTkFrame(p, fg_color="transparent")
        head.pack(fill="x", padx=2, pady=(0, 4))
        self._reg(ctk.CTkLabel(head, text=self.T("tab_review"), font=self.f_sec, text_color=INK), "tab_review").pack(side="left")
        self._reg(ghost(head, self.T("b_refresh"), self.refresh_reviews, 80), "b_refresh").pack(side="right")
        self._reg(ctk.CTkLabel(p, text=self.T("review_hint"), font=self.f_s, text_color=MUTED),
                  "review_hint").pack(anchor="w", padx=2, pady=(0, 6))
        self.rev_list = ctk.CTkScrollableFrame(p, fg_color="transparent")
        self.rev_list.pack(fill="both", expand=True, padx=0, pady=(2, 4))

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self.root, fg_color=BG_WINDOW, corner_radius=0, height=26)
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_propagate(False)
        self.lbl_info = ctk.CTkLabel(bar, text=self._cadence_text(), font=self.f_s, text_color=MUTED)
        self.lbl_info.pack(side="left", padx=16)
        self.lbl_quota = ctk.CTkLabel(bar, text="", font=self.f_s, text_color=MUTED)
        self.lbl_quota.pack(side="right", padx=16)

    # ---------- 运行参数(主界面即改即存) ----------
    def _get_cfg(self, path, default=None):
        node = self.cfg
        for k in path.split("."):
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def _set_cfg(self, path, val):
        node = self.cfg
        keys = path.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = val

    def _save_cfg(self):
        try:
            save_config(self.cfg, CONFIG)
        except Exception as e:
            self._log(f"保存配置失败: {e!r}")

    def _apply_param_int(self, cfg_path, entry):
        txt = entry.get().strip()
        try:
            v = int(txt)
            assert v >= 0
        except Exception:
            entry.delete(0, "end")
            entry.insert(0, str(self._get_cfg(cfg_path, 0)))   # 非法输入 → 还原
            return
        if v != self._get_cfg(cfg_path):
            self._set_cfg(cfg_path, v)
            self._save_cfg()
            self.lbl_info.configure(text=self._cadence_text())

    def _pick_outdir(self):
        d = filedialog.askdirectory(title="选择输出文件夹")
        if d:
            self._set_cfg("paths.output", d)
            self._save_cfg()
            self.lbl_outdir.configure(text=self._short_path(d))

    def _refresh_params_from_cfg(self):
        """从 self.cfg 把运行参数回填到主界面控件(设置里改完后同步)。"""
        try:
            for e, path in [(self.e_debounce, "sheet.confirm_delay_seconds"),
                            (self.e_poll, "sheet.poll_seconds"),
                            (self.e_sellers, "collect.max_sellers")]:
                e.delete(0, "end")
                e.insert(0, str(self._get_cfg(path, "")))
            self.lbl_outdir.configure(text=self._short_path(self.cfg["paths"].get("output", "./输出")))
            self.lbl_info.configure(text=self._cadence_text())
        except Exception:
            pass

    @staticmethod
    def _short_path(p, maxlen=52):
        p = str(p)
        if len(p) <= maxlen:
            return p
        return p[:maxlen // 2 - 2] + " … " + p[-(maxlen // 2 - 1):]

    def _cadence_text(self):
        s = self.cfg["sheet"]
        col = self.cfg.get("collect", {})
        p, d, n = s.get("poll_seconds", 30), s.get("confirm_delay_seconds", 180), col.get("max_sellers", 6)
        if self.lang == "en":
            return f"Poll every {p}s · debounce {d}s · collect {n} sellers"
        return f"每 {p}s 查表 · 确认后去抖 {d}s · 采集 {n} 家"

    # ---------- 监听 ----------
    def _reporter(self, ev):
        self.q.put(ev)

    def toggle(self):
        if self.thread and self.thread.is_alive():
            s = self.stats
            msg = self.T("stop_msg").format(t=s["total"], d=s["done"], r=s["review"], e=s["err"])
            if ask_confirm(self, self.T("stop_title"), msg, ok_text=self.T("stop_ok"),
                           ok_color=ERR_C, ok_ink="#ffffff", ok_hover="#DC3E43"):
                self.stop()
        else:
            self.start()

    def _set_toggle(self, running):
        if running:
            self.btn_toggle.configure(text=self.T("btn_stop"), fg_color=ERR_C, text_color=ON_ACCENT,
                                      border_width=0, hover_color="#DC3E43")
        else:
            self.btn_toggle.configure(text=self.T("btn_start"), fg_color=ACCENT, text_color=ON_ACCENT,
                                      border_width=0, hover_color=ACCENT_HOVER)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event = threading.Event()

        def run():
            # Watcher 构造(可能取钉钉 token、读表)放线程里,避免阻塞界面
            try:
                w = Watcher(self.cfg, reporter=self._reporter, learner=self.learner)
            except Exception as e:
                self._reporter({"type": "monitor_error", "msg": f"创建监听失败: {e!r}"})
                self.running = False
                self.root.after(0, lambda: (self._set_toggle(False), self._set_status("error")))
                return
            w.run_loop(self.stop_event)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.running = True
        self._set_toggle(True)
        self._set_status("running")
        self._log("监听已开始")

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        self.running = False
        self._set_toggle(False)
        self._set_status("stopped")
        self._log("监听已停止")

    def _set_status(self, mode):
        self._status_mode = mode
        styles = {"running": ("st_running", "#1E7A48", "#E6F4EC"),
                  "stopped": ("st_stopped", "#5A6473", "#F0F1F3"),
                  "error": ("st_error", "#B26608", "#FBF0DF")}
        key, fg, bg = styles.get(mode, styles["stopped"])
        self.side_status.configure(text="  ● " + self.T(key) + "  ", text_color=fg, fg_color=bg)

    def _drain(self):
        try:
            while True:
                ev = self.q.get_nowait()
                try:
                    self._handle(ev)
                except Exception as e:
                    print("处理事件出错:", repr(e))
        except queue.Empty:
            pass
        finally:
            # 无论如何都要重新排程,否则界面停止刷新
            self._save_ticks += 1
            if self._save_ticks % 25 == 0:
                self._save_ui_state()
            self.root.after(400, self._drain)

    def _handle(self, ev):
        t = ev.get("type")
        if t == "order":
            self.stats["total"] += 1
            st = ev.get("status", "")
            for k, name in [("done", "已完成"), ("none", "无匹配"), ("review", "待复核"), ("err", "错误")]:
                if st == name:
                    self.stats[k] += 1
            self.stats["images"] += int(ev.get("images") or 0)
            self._refresh_metrics()
            dd = " (去重复用)" if ev.get("dedup") else ""
            self._log(f"{ev.get('order_id')}  {st}  卖家={ev.get('sellers')} 图={ev.get('images')}{dd}")
            if st == "待复核":
                self.refresh_reviews()
        elif t == "learn":
            self._log("【学习】" + ev.get("msg", ""))
        elif t == "monitor_error":
            self._log("【监听异常】" + ev.get("msg", ""))
            if self.running:
                self._set_status("error")
        elif t == "error":
            self._log("【异常】" + ev.get("msg", ""))
        elif t == "tick":
            self.lbl_info.configure(text=self._cadence_text() + f"  ·  上次检查 {ev.get('at','')}")
            if self.running:
                self._set_status("running")

    def _refresh_metrics(self):
        colors = {"err": ERR_C if self.stats["err"] else INK,
                  "review": WARN_C if self.stats["review"] else INK,
                  "done": OK_C if self.stats["done"] else INK}
        for k, v in self.metric_lbls.items():
            v.configure(text=str(self.stats.get(k, 0)), text_color=colors.get(k, INK))

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        try:  # 限制日志行数,避免长时间运行文本框膨胀变卡
            n = int(self.log.index("end-1c").split(".")[0])
            if n > 1000:
                self.log.delete("1.0", f"{n - 800}.0")
        except Exception:
            pass
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- 待复核 ----------
    def refresh_reviews(self):
        if not hasattr(self, "rev_list"):
            return
        for w in self.rev_list.winfo_children():
            w.destroy()
        pend = review_mod.list_pending(self.cfg["paths"].get("review", "./复核"))
        if not pend:
            ctk.CTkLabel(self.rev_list, text=self.T("review_empty"), font=self.f_n, text_color=MUTED).pack(pady=26)
            return
        for rec in pend:
            row = ctk.CTkFrame(self.rev_list, fg_color=BG_CARD, corner_radius=8, border_width=1, border_color=LINE_HAIR)
            row.pack(fill="x", pady=4, padx=2)
            ctk.CTkLabel(row, text=f"{self.T('review_order')} {rec['order_id']}", font=self.f_n,
                         text_color=INK).pack(side="left", padx=16, pady=11)
            ctk.CTkLabel(row, text=f"{len(rec.get('candidates', []))}{self.T('review_cands')}", font=self.f_s,
                         text_color=MUTED).pack(side="left")
            ctk.CTkButton(row, text=self.T("review_btn"), width=74, height=32, corner_radius=6, fg_color=ACCENT,
                          hover_color=ACCENT_HOVER, text_color=ON_ACCENT, font=self.f_s,
                          command=lambda r=rec: ReviewWindow(self, r)).pack(side="right", padx=12)

    # ---------- 工具 ----------
    def open_output(self):
        d = os.path.abspath(self.cfg["paths"].get("output", "./输出"))
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)
        except Exception:
            messagebox.showinfo("路径", d)

    def check_now(self):
        def job():
            try:
                Watcher(self.cfg, reporter=self._reporter, learner=self.learner).tick()
                self._reporter({"type": "tick", "at": time.strftime("%H:%M:%S")})
            except Exception as e:
                self._reporter({"type": "error", "msg": f"立即检查: {e!r}"})
        threading.Thread(target=job, daemon=True).start()

    def show_egress_ip(self):
        """探测当前出口 IP,并直接问钉钉「你看到我的 IP 是多少」——即白名单要填的那个。"""
        self._log("正在检测出口 IP 与钉钉读表 ...")

        def job():
            import re
            import requests
            lines = []
            # 1) 通用出口(国内 IP 回显,直连探测)
            try:
                t = requests.get("https://myip.ipip.net", timeout=12).text.strip()
                lines.append("通用出口探测:" + t)
            except Exception as e:
                lines.append("通用出口探测失败:" + repr(e)[:80])
            # 2) 钉钉实际看到的出口 IP(权威,白名单填这个)
            dt = self.cfg.get("sheet", {}).get("dingtalk", {})
            dingtalk_ip = None
            try:
                tok = requests.post("https://api.dingtalk.com/v1.0/oauth2/accessToken",
                                    json={"appKey": dt.get("app_key"), "appSecret": dt.get("app_secret")},
                                    timeout=20).json().get("accessToken")
                url = (f"https://api.dingtalk.com/v1.0/doc/workbooks/{dt.get('workbook_id')}"
                       f"/sheets/{dt.get('sheet_id')}/ranges/{dt.get('read_range')}")
                rr = requests.get(url, headers={"x-acs-dingtalk-access-token": tok},
                                  params={"operatorId": dt.get("operator_id")}, timeout=20)
                if rr.status_code == 200:
                    lines.append("钉钉读表:✔ 正常(200),当前出口 IP 已在白名单内。")
                else:
                    m = re.search(r"request ip=([0-9a-fA-F:.]+)", rr.text)
                    dingtalk_ip = m.group(1) if m else None
                    lines.append(f"钉钉读表:✗ 失败 HTTP {rr.status_code}")
                    if dingtalk_ip:
                        lines.append(f"钉钉看到的出口 IP = {dingtalk_ip}")
                    if "IpNotInWhiteList" in rr.text and dingtalk_ip:
                        lines.append(f"→ 该 IP 不在白名单。请到钉钉开放平台把\n   {dingtalk_ip}\n   加入「服务器出口 IP 白名单」后保存,再点开始监听。")
            except Exception as e:
                lines.append("钉钉探测失败:" + repr(e)[:120])
            msg = "\n".join(lines)
            self.root.after(0, lambda: (self._log("出口IP检测:" + " | ".join(lines)),
                                        messagebox.showinfo("当前出口 IP / 钉钉复检", msg)))
        threading.Thread(target=job, daemon=True).start()

    def run_single(self):
        RunSingleWindow(self)

    def open_cleanup(self):
        CleanupWindow(self)

    def _run_single_job(self, oid, url):
        def job():
            try:
                col = self.cfg.get("collect", {})
                r = pipeline.process_order(
                    self.api, matcher, self.cfg["matcher"], oid, url,
                    self.cfg["paths"].get("output", "./输出"),
                    {"max_per": int(col.get("max_sellers", 6)),
                     "max_scan": int(col.get("max_scan", 25)),
                     "max_detail": int(col.get("max_detail", 30)),
                     "rerun_extra": int(col.get("rerun_extra", 3))},
                    work=self.cfg["paths"].get("work", "./_pilot_work"),
                    junk_cfg=self.cfg.get("junk_filter"),
                    img_dedup=self.cfg.get("thresholds", {}).get("img_dedup", 5))
                self._reporter({"type": "order", "order_id": oid,
                                "status": {"DONE": "已完成", "REVIEW": "待复核", "NONE": "无匹配"}.get(r["status"], r["status"]),
                                "sellers": r.get("sellers"), "images": r.get("saved_images")})
            except Exception as e:
                self._reporter({"type": "error", "msg": f"跑单 {oid}: {e!r}"})
        threading.Thread(target=job, daemon=True).start()

    def export_reviews(self):
        p = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="复核记录.csv")
        if not p:
            return

        def job():  # 读 sqlite 放线程,避免阻塞界面
            try:
                n = self.learner.export_csv(p)
                st = self.learner.stats()
                self.root.after(0, lambda: messagebox.showinfo(
                    "导出完成", f"已导出 {n} 条复核记录\n对 {st['对']} / 误配 {st['误配']}"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("失败", str(e)))
        threading.Thread(target=job, daemon=True).start()

    def export_diag(self):
        p = filedialog.asksaveasfilename(defaultextension=".zip", initialfile="诊断包.zip")
        if not p:
            return
        base = p[:-4] if p.endswith(".zip") else p

        log_dir = self.cfg["paths"].get("log", "./日志")
        dt = self.cfg.get("sheet", {}).get("dingtalk", {})
        secrets = [str(v) for v in (self.cfg.get("api", {}).get("key"), self.cfg.get("api", {}).get("secret"),
                                    dt.get("app_key"), dt.get("app_secret"), dt.get("operator_id"))
                   if v and len(str(v)) >= 4]

        def job():  # 压缩日志放线程;先把日志里的 key/secret 脱敏,避免诊断包外发泄露
            import tempfile
            stage = tempfile.mkdtemp(prefix="diag_")
            try:
                dstroot = os.path.join(stage, "日志")
                for root_, _dirs, files in os.walk(log_dir):
                    outd = os.path.join(dstroot, os.path.relpath(root_, log_dir))
                    os.makedirs(outd, exist_ok=True)
                    for fn in files:
                        src, dst = os.path.join(root_, fn), os.path.join(outd, fn)
                        if fn.lower().endswith((".jsonl", ".log", ".txt", ".json", ".csv")):
                            try:
                                t = open(src, encoding="utf-8", errors="replace").read()
                                for s in secrets:
                                    t = t.replace(s, "***REDACTED***")
                                open(dst, "w", encoding="utf-8").write(t)
                                continue
                            except Exception:
                                pass
                        try:
                            shutil.copy2(src, dst)
                        except Exception:
                            pass
                shutil.make_archive(base, "zip", stage)
                self.root.after(0, lambda: messagebox.showinfo("导出完成", f"诊断包已导出(密钥已脱敏):\n{base}.zip"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("失败", str(e)))
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        threading.Thread(target=job, daemon=True).start()

    def open_settings(self):
        SettingsWindow(self)

    # ---------- 状态记忆 / 托盘 / 关闭 ----------
    def _load_ui_state(self):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            return {}

    def _save_ui_state(self):
        try:
            st = {"geometry": self.root.geometry(), "lang": self.lang}
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False)
        except Exception:
            pass

    def _on_close(self):
        self._save_ui_state()
        if _TRAY_OK:
            self.root.withdraw()
            self._ensure_tray()
        else:
            if messagebox.askokcancel("退出", "关闭窗口将停止监听并退出。确定?"):
                self.stop()
                self.root.destroy()

    def _ensure_tray(self):
        if self.tray:
            return
        img = _PILImage.new("RGB", (64, 64), (124, 131, 255))
        menu = pystray.Menu(pystray.MenuItem("显示控制台", self._tray_show, default=True),
                            pystray.MenuItem("退出", self._tray_quit))
        self.tray = pystray.Icon("sourcing", img, "实拍图采集(后台运行)", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _tray_show(self, *a):
        self.root.after(0, self.root.deiconify)

    def _tray_quit(self, *a):
        self._save_ui_state()
        self.stop()
        if self.tray:
            self.tray.stop()
        self.root.after(0, self.root.destroy)


class ReviewWindow:
    def __init__(self, app, rec):
        self.app, self.rec, self.vars, self._imgs = app, rec, {}, []
        w = ctk.CTkToplevel(app.root)
        w.title(app.T("rev_title").format(id=rec['order_id']))
        w.geometry("960x640")
        w.configure(fg_color=BG_WINDOW)
        self.w = w
        ctk.CTkLabel(w, text=app.T("rev_instr"),
                     font=app.f_s, text_color=MUTED).pack(fill="x", padx=18, pady=(14, 6))
        body = ctk.CTkFrame(w, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14)
        left = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=8, border_width=1, border_color=LINE_HAIR)
        left.pack(side="left", fill="y", padx=6, pady=6)
        ctk.CTkLabel(left, text=app.T("rev_customer"), font=app.f_n, text_color=INK).pack(pady=(14, 4))
        self._show_img(left, rec.get("customer_image", ""), 250)
        right = ctk.CTkScrollableFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        for i, c in enumerate(rec.get("candidates", [])):
            cell = ctk.CTkFrame(right, fg_color=BG_PANEL, corner_radius=8, border_width=1, border_color=LINE_HAIR)
            cell.grid(row=i // 3, column=i % 3, padx=6, pady=6, sticky="n")
            self._show_img(cell, c.get("image_url", ""), 150)
            var = BooleanVar()
            self.vars[c["offer_id"]] = var
            ctk.CTkCheckBox(cell, text=f"{app.T('rev_same')}  {c['offer_id']}", variable=var, font=app.f_s,
                            fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(padx=8, pady=(2, 10))
        foot = ctk.CTkFrame(w, fg_color="transparent")
        foot.pack(fill="x", padx=18, pady=12)
        ctk.CTkButton(foot, text=app.T("rev_submit"), command=self._submit, height=38, corner_radius=6,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ON_ACCENT, font=app.f_n).pack(side="left")
        ghost(foot, app.T("rev_reject"), lambda: self._submit(reject=True), 160).pack(side="left", padx=10)

    def _show_img(self, parent, url, size):
        lbl = ctk.CTkLabel(parent, text=self.app.T("img_loading"), width=size, height=size,
                           font=self.app.f_s, text_color=MUTED)
        lbl.pack(padx=10, pady=6)
        if not (_IMG_OK and url):
            lbl.configure(text=self.app.T("img_none"))
            return

        def load_one(u):
            if u.startswith("http"):
                data = requests.get(u, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).content
                return Image.open(io.BytesIO(data)).convert("RGB")
            return Image.open(u).convert("RGB")

        def job():
            variants = [url]
            if url.lower().split("?")[0].endswith(".avif"):
                variants.append(url[:url.lower().rfind(".avif")])
            for u in variants:
                try:
                    im = load_one(u)
                    im.thumbnail((size, size))
                    self.app.root.after(0, lambda im=im: self._set_img(lbl, im))
                    return
                except Exception:
                    continue
            self.app.root.after(0, lambda: lbl.configure(text=self.app.T("img_fail")))
        threading.Thread(target=job, daemon=True).start()

    def _set_img(self, lbl, im):
        ph = ctk.CTkImage(light_image=im, size=im.size)
        self._imgs.append(ph)
        lbl.configure(image=ph, text="")

    def _submit(self, reject=False):
        chosen = [] if reject else [oid for oid, v in self.vars.items() if v.get()]
        self.w.destroy()

        def job():
            try:
                from sheets import make_backend
                try:
                    backend = make_backend(self.app.cfg["sheet"], self.app.cfg["paths"].get("work", "./_pilot_work"))
                except Exception:
                    backend = None
                r = review_mod.submit(self.app.api, self.app.cfg, self.app.learner, backend, self.rec, chosen)
                self.app._reporter({"type": "order", "order_id": self.rec["order_id"],
                                    "status": r["status"], "sellers": len(chosen), "images": r["saved_images"]})
            except Exception as e:
                self.app._reporter({"type": "error", "msg": f"复核提交 {self.rec['order_id']}: {e!r}"})
            self.app.root.after(0, self.app.refresh_reviews)
        threading.Thread(target=job, daemon=True).start()


class RunSingleWindow:
    def __init__(self, app):
        self.app = app
        w = ctk.CTkToplevel(app.root)
        w.title(app.T("run_title"))
        w.geometry("620x360")
        w.configure(fg_color=BG_WINDOW)
        self.w = w
        card = ctk.CTkFrame(w, fg_color=BG_PANEL, corner_radius=8, border_width=1, border_color=LINE_HAIR)
        card.pack(fill="both", expand=True, padx=18, pady=18)
        ctk.CTkLabel(card, text=app.T("run_title"), font=app.f_h1, text_color=INK).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(card, text=app.T("run_desc"), wraplength=520, justify="left",
                     font=app.f_s, text_color=MUTED).pack(anchor="w", padx=20)
        ctk.CTkLabel(card, text=app.T("run_id"), font=app.f_n, text_color=SUBINK).pack(anchor="w", padx=20, pady=(18, 2))
        self.e_id = ctk.CTkEntry(card, height=36, font=app.f_n, border_color=LINE_SOFT, corner_radius=6,
                                 placeholder_text=app.T("run_ph_id"))
        self.e_id.pack(fill="x", padx=20)
        ctk.CTkLabel(card, text=app.T("run_url"), font=app.f_n, text_color=SUBINK).pack(anchor="w", padx=20, pady=(14, 2))
        self.e_url = ctk.CTkEntry(card, height=36, font=app.f_n, border_color=LINE_SOFT, corner_radius=6,
                                  placeholder_text="https://...")
        self.e_url.pack(fill="x", padx=20)
        ctk.CTkButton(card, text=app.T("run_run"), command=self._run, height=36, width=120, corner_radius=6,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ON_ACCENT, font=app.f_n).pack(anchor="e", padx=20, pady=20)
        w.after(200, self.e_id.focus)

    def _run(self):
        oid, url = self.e_id.get().strip(), self.e_url.get().strip()
        if not oid or not url:
            messagebox.showinfo(self.app.T("tip"), self.app.T("run_need"))
            return
        running = bool(self.app.thread and self.app.thread.is_alive())
        short = url if len(url) <= 52 else url[:49] + "..."
        msg = self.app.T("run_cfm_msg").format(oid=oid, url=short)
        if running:
            msg += self.app.T("run_cfm_parallel")
        if not ask_confirm(self.app, self.app.T("run_cfm_title"), msg, ok_text=self.app.T("run_cfm_ok")):
            return
        self.w.destroy()
        self.app._run_single_job(oid, url)


class CleanupWindow:
    """清理旧输出:设天数 → 扫描列出 → 二次确认 → 删除。"""
    def __init__(self, app):
        self.app = app
        self.found = []
        w = ctk.CTkToplevel(app.root)
        w.title(app.T("clean_title"))
        w.geometry("560x540")
        w.configure(fg_color=BG_WINDOW)
        self.w = w
        card = ctk.CTkFrame(w, fg_color=BG_PANEL, corner_radius=8, border_width=1, border_color=LINE_HAIR)
        card.pack(fill="both", expand=True, padx=16, pady=16)
        ctk.CTkLabel(card, text=app.T("clean_title"), font=app.f_h1, text_color=INK).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(card, text=app.T("clean_desc"),
                     font=app.f_s, text_color=MUTED, wraplength=490, justify="left").pack(anchor="w", padx=20)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(row, text=app.T("clean_days_lbl"), font=app.f_n, text_color=SUBINK).pack(side="left")
        self.e_days = ctk.CTkEntry(row, width=76, height=34, border_color=LINE_SOFT, corner_radius=6, font=app.f_n)
        self.e_days.pack(side="left", padx=10)
        self.e_days.insert(0, str(app.cfg.get("cleanup", {}).get("keep_days", 30)))
        ctk.CTkButton(row, text=app.T("clean_scan"), width=88, height=34, corner_radius=6, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color=ON_ACCENT, font=app.f_n,
                      command=self._scan).pack(side="left")
        self.lbl = ctk.CTkLabel(card, text=app.T("clean_hint"), font=app.f_s, text_color=MUTED)
        self.lbl.pack(anchor="w", padx=20, pady=(6, 4))
        self.box = ctk.CTkTextbox(card, font=ctk.CTkFont("Consolas", 12), fg_color=LOGBG,
                                  text_color=LOGINK, corner_radius=8, border_width=1, border_color=LINE_HAIR)
        self.box.pack(fill="both", expand=True, padx=18, pady=8)
        self.box.configure(state="disabled")
        foot = ctk.CTkFrame(card, fg_color="transparent")
        foot.pack(fill="x", padx=20, pady=(4, 16))
        self.btn_del = ctk.CTkButton(foot, text=app.T("clean_del"), width=140, height=38, corner_radius=6,
                                     fg_color=ERR_C, hover_color="#DC3E43", text_color="#ffffff",
                                     font=app.f_n, command=self._delete, state="disabled")
        self.btn_del.pack(side="left")
        ghost(foot, app.T("d_close"), w.destroy, 88).pack(side="left", padx=10)

    def _out_root(self):
        return os.path.abspath(self.app.cfg["paths"].get("output", "./输出"))

    def _days(self):
        try:
            d = int(self.e_days.get().strip())
            return d if d >= 0 else None
        except Exception:
            return None

    def _scan(self):
        T = self.app.T
        days = self._days()
        if days is None:
            messagebox.showinfo(T("tip"), T("clean_need_days"))
            return
        self.found = cleanup.find_old_dirs(self._out_root(), days)
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        if not self.found:
            self.box.insert("end", T("clean_none").format(days=days) + "\n")
            self.btn_del.configure(state="disabled")
        else:
            for d in self.found:
                self.box.insert("end", T("clean_row").format(name=d["name"], created=d["created"], age=d["age_days"]) + "\n")
            self.btn_del.configure(state="normal")
        self.box.configure(state="disabled")
        self.lbl.configure(text=T("clean_found").format(n=len(self.found), days=days))

    def _delete(self):
        if not self.found:
            return
        T = self.app.T
        days = self._days()
        msg = T("clean_cfm_msg").format(n=len(self.found), days=days)
        if not ask_confirm(self.app, T("clean_cfm_title"), msg, ok_text=T("clean_cfm_ok"),
                           ok_color=ERR_C, ok_ink="#ffffff", ok_hover="#DC3E43"):
            return
        self.app.cfg.setdefault("cleanup", {})["keep_days"] = days   # 记住设定
        dirs = self.found
        self.w.destroy()

        def job():
            ok, fail = cleanup.delete_dirs(dirs)
            purged = 0
            try:  # 同步清掉被删目录对应的去重缓存条目,避免"命中缓存却复制空目录"
                from store import Store
                st = Store(self.app.cfg["paths"].get("cache", "./缓存/cache.sqlite"))
                purged = st.delete_by_names([d["name"] for d in dirs])
                st.close()
            except Exception:
                pass
            m = T("clean_done_msg").format(ok=ok) + (T("clean_done_fail").format(n=len(fail)) if fail else "")

            def done():
                self.app._log(f"清理旧输出:删除 {ok} 个" + (f",失败 {len(fail)}" if fail else "")
                              + (f",清缓存 {purged} 条" if purged else ""))
                messagebox.showinfo(T("clean_done_title"), m)
            self.app.root.after(0, done)
        threading.Thread(target=job, daemon=True).start()


class SettingsWindow:
    FIELDS = [
        ("api.key", "f_api_key"), ("api.secret", "f_api_secret"),
        ("sheet.confirm_delay_seconds", "f_debounce"), ("sheet.poll_seconds", "f_poll"),
        ("collect.max_sellers", "f_sellers"),
        ("cleanup.keep_days", "f_keepdays"),
        ("sheet.backend", "f_backend"),
        ("sheet.dingtalk.app_key", "f_dt_appkey"), ("sheet.dingtalk.app_secret", "f_dt_appsecret"),
        ("sheet.dingtalk.workbook_id", "f_dt_workbook"), ("sheet.dingtalk.sheet_id", "f_dt_sheet"),
        ("sheet.dingtalk.operator_id", "f_dt_operator"),
        ("paths.output", "f_output"),
    ]

    def __init__(self, app):
        self.app = app
        w = ctk.CTkToplevel(app.root)
        w.title(app.T("set_title"))
        w.geometry("580x560")
        w.configure(fg_color=BG_WINDOW)
        self.entries = {}
        ctk.CTkLabel(w, text=app.T("set_title"), font=app.f_h1, text_color=INK).pack(anchor="w", padx=20, pady=(16, 2))
        frm = ctk.CTkScrollableFrame(w, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=16, pady=8)
        for path, label_key in self.FIELDS:
            ctk.CTkLabel(frm, text=app.T(label_key), font=app.f_s, text_color=SUBINK, anchor="w").pack(fill="x", pady=(8, 2))
            if path == "paths.output":
                rowf = ctk.CTkFrame(frm, fg_color="transparent")
                rowf.pack(fill="x")
                e = ctk.CTkEntry(rowf, height=34, corner_radius=6, border_color=LINE_SOFT)
                e.pack(side="left", fill="x", expand=True)
                ctk.CTkButton(rowf, text=app.T("set_pickdir"), width=104, height=34, corner_radius=6,
                              fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ON_ACCENT, font=app.f_s,
                              command=lambda en=e: self._pick_dir(en)).pack(side="left", padx=(8, 0))
            else:
                e = ctk.CTkEntry(frm, width=520, height=34, corner_radius=6, border_color=LINE_SOFT)
                e.pack(fill="x")
            e.insert(0, str(self._get(path, "")))
            self.entries[path] = e
        ctk.CTkButton(w, text=app.T("set_save"), command=lambda: self._save(w), height=38, width=120, corner_radius=6,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ON_ACCENT).pack(pady=(4, 8))
        ctk.CTkLabel(w, text=app.T("set_hint"), font=app.f_s, text_color=MUTED,
                     wraplength=540, justify="left").pack(pady=(0, 10))

    def _pick_dir(self, entry):
        d = filedialog.askdirectory(title=self.app.T("set_pickdir"))
        if d:
            entry.delete(0, "end")
            entry.insert(0, d)

    def _get(self, path, default):
        node = self.app.cfg
        for k in path.split("."):
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def _set(self, path, val):
        node = self.app.cfg
        keys = path.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        if isinstance(node.get(keys[-1]), int):
            try:
                val = int(val)
            except ValueError:
                pass
        node[keys[-1]] = val

    def _save(self, w):
        T = self.app.T
        running = bool(self.app.thread and self.app.thread.is_alive())
        msg = T("set_cfm_msg") + (T("set_cfm_running") if running else "")
        if not ask_confirm(self.app, T("set_cfm_title"), msg, ok_text=T("set_cfm_ok")):
            return
        for path, e in self.entries.items():
            self._set(path, e.get())
        save_config(self.app.cfg, CONFIG)
        self.app._refresh_params_from_cfg()   # 同步回主界面的运行参数控件
        messagebox.showinfo(T("set_saved_title"), T("set_saved_msg"))
        w.destroy()


if __name__ == "__main__":
    os.chdir(app_dir())
    cfg = load_config(CONFIG)
    lock_path = os.path.join(cfg.get("paths", {}).get("work", "./_pilot_work"), "collector.lock")
    with SingleInstance(lock_path):
        root = ctk.CTk()
        App(root)
        root.mainloop()

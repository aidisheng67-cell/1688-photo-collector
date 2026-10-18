"""
sheets.py —— 共享表格后端（可插拔）。
统一接口：read_rows() 读出每行 {id,image_url,confirm,status,_rownum}；write_back() 回写。
后端：WPSSheet(金山文档/WPS在线表格API) + XlsxSheet(本地xlsx,测试用)。
列名→逻辑字段 由 config.sheet.columns 配置。
"""
import json
import time

import requests


def _col_letter(idx0):
    s, n = "", idx0 + 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class _Base:
    def __init__(self, cols, confirm_values):
        self.cols = cols
        self.confirm_values = [str(v).strip().lower() for v in confirm_values]

    def _is_confirm(self, v):
        return str(v).strip().lower() in self.confirm_values

    def read_rows(self):
        raise NotImplementedError

    def write_back(self, rownum, fields):
        raise NotImplementedError


# ---------------- 金山文档 / WPS 在线表格 ----------------
class WPSSheet(_Base):
    """
    金山文档开放平台·在线表格(ksheet)。
    读：GET  {base}/api/v1/openapi/ksheet/{file_token}/sheets/{sheet_idx}/cells
    写：POST {base}/api/v1/openapi/ksheet/{file_token}/sheets/{sheet_idx}/cells
    鉴权：OAuth access_token。
    # 待对接(企业应用审核通过后,用真实凭证核对)：base host、鉴权头格式、range 参数名、返回字段路径。
    程序会把首个返回落盘 _pilot_work/last_wps_*.json 便于核对。
    """
    def __init__(self, cfg, cols, confirm_values, work="./_pilot_work"):
        super().__init__(cols, confirm_values)
        self.base = cfg.get("base_url", "https://www.kdocs.cn").rstrip("/")
        self.app_id = cfg.get("app_id", "")
        self.app_secret = cfg.get("app_secret", "")
        self.access_token = cfg.get("access_token", "")
        self.file_token = cfg.get("file_token", "")
        self.sheet_idx = cfg.get("sheet_idx", 0)
        self.read_range = cfg.get("read_range", "A1:Z2000")
        self.work = work
        self._hdr_idx = {}

    def _h(self):
        # # 待对接：金山文档实际鉴权头(可能是 Authorization: Bearer 或自定义头)
        return {"Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"}

    def _url(self):
        return f"{self.base}/api/v1/openapi/ksheet/{self.file_token}/sheets/{self.sheet_idx}/cells"

    def read_rows(self):
        r = requests.get(self._url(), headers=self._h(),
                         params={"range": self.read_range}, timeout=30)
        try:
            data = r.json()
        except ValueError:
            data = {"_raw": r.text, "_status": r.status_code}
        try:
            json.dump(data, open(f"{self.work}/last_wps_read.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception:
            pass
        r.raise_for_status()
        # # 待对接：确认返回里二维值的字段路径(下面按常见 data.values / values 兼容)
        values = (data.get("data") or {}).get("values") or data.get("values") or []
        if not values:
            return []
        header = [str(x).strip() for x in values[0]]
        self._hdr_idx = {name: i for i, name in enumerate(header)}
        out = []
        for ri, row in enumerate(values[1:], start=2):
            def g(field):
                j = self._hdr_idx.get(self.cols.get(field))
                return row[j] if (j is not None and j < len(row)) else ""
            out.append({"id": str(g("id")).strip(),
                        "image_url": str(g("image_url")).strip(),
                        "confirm": self._is_confirm(g("confirm")),
                        "status": str(g("status")).strip(),
                        "_rownum": ri})
        return out

    def write_back(self, rownum, fields):
        cells = {}
        for field, val in fields.items():
            j = self._hdr_idx.get(self.cols.get(field))
            if j is not None:
                cells[f"{_col_letter(j)}{rownum}"] = val
        if not cells:
            return
        # # 待对接：确认写入 body 结构(下面按 {cells:{A1:val,...}} 占位)
        requests.post(self._url(), headers=self._h(),
                      json={"cells": cells}, timeout=30).raise_for_status()


# ---------------- 钉钉在线表格 ----------------
class DingTalkSheet(_Base):
    """
    钉钉在线表格(钉钉文档)。鉴权:企业内部应用 app_key/app_secret -> accessToken(2h,自动续)。
    读:GET  .../v1.0/doc/workbooks/{workbook_id}/sheets/{sheet_id}/ranges/{range}?operatorId=..
    写:PUT  .../ranges/{cell}   头 x-acs-dingtalk-access-token
    需 operatorId(有该表权限的人的 unionId);workbook_id/sheet_id 在表格 URL 里;应用需配 IP 白名单。
    """
    def __init__(self, cfg, cols, confirm_values, work="./_pilot_work"):
        super().__init__(cols, confirm_values)
        self.app_key = cfg.get("app_key", "")
        self.app_secret = cfg.get("app_secret", "")
        self.workbook = cfg.get("workbook_id", "")
        self.sheet = cfg.get("sheet_id", "")
        self.operator = cfg.get("operator_id", "")
        self.read_range = cfg.get("read_range", "A1:Z2000")
        self.base = "https://api.dingtalk.com/v1.0/doc"
        self.work = work
        self._tok = None
        self._tok_exp = 0
        self._hdr_idx = {}

    def _token(self):
        if self._tok and time.time() < self._tok_exp - 120:
            return self._tok
        r = requests.post("https://api.dingtalk.com/v1.0/oauth2/accessToken",
                          json={"appKey": self.app_key, "appSecret": self.app_secret}, timeout=30)
        r.raise_for_status()
        d = r.json()
        if not d.get("accessToken"):
            raise RuntimeError(f"钉钉鉴权失败: {d.get('code')} {d.get('message')}")
        self._tok = d["accessToken"]
        self._tok_exp = time.time() + int(d.get("expireIn", 7200))
        return self._tok

    def _h(self):
        return {"x-acs-dingtalk-access-token": self._token(), "Content-Type": "application/json"}

    def _range_url(self, rng):
        return f"{self.base}/workbooks/{self.workbook}/sheets/{self.sheet}/ranges/{rng}"

    def read_rows(self):
        r = requests.get(self._range_url(self.read_range), headers=self._h(),
                         params={"operatorId": self.operator}, timeout=30)
        r.raise_for_status()
        values = r.json().get("values") or []
        if not values:
            return []
        header = [str(x).strip() for x in values[0]]
        self._hdr_idx = {name: i for i, name in enumerate(header)}
        out = []
        for ri, row in enumerate(values[1:], start=2):
            def g(field):
                j = self._hdr_idx.get(self.cols.get(field))
                return row[j] if (j is not None and j < len(row)) else ""
            out.append({"id": str(g("id")).strip(), "image_url": str(g("image_url")).strip(),
                        "confirm": self._is_confirm(g("confirm")), "status": str(g("status")).strip(),
                        "_rownum": ri})
        return out

    def write_back(self, rownum, fields):
        for field, val in fields.items():
            j = self._hdr_idx.get(self.cols.get(field))
            if j is None:
                continue
            cell = f"{_col_letter(j)}{rownum}"
            requests.put(self._range_url(cell), headers=self._h(),
                         params={"operatorId": self.operator},
                         json={"values": [[val]]}, timeout=30).raise_for_status()


# ---------------- 飞书多维表格 (Bitable) ----------------
class FeishuSheet(_Base):
    """
    飞书多维表格。鉴权:自建应用 app_id/app_secret -> tenant_access_token(2h,自动续)。
    读:GET  /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
    写:PUT  .../records/{record_id}   (飞书按 record_id 定位行,无行号)
    需应用权限:bitable:record:read / bitable:record:write。
    app_token、table_id 在多维表格的 URL 里。
    """
    def __init__(self, cfg, cols, confirm_values, work="./_pilot_work"):
        super().__init__(cols, confirm_values)
        self.base = cfg.get("base_url", "https://open.feishu.cn").rstrip("/")
        self.app_id = cfg.get("app_id", "")
        self.app_secret = cfg.get("app_secret", "")
        self.app_token = cfg.get("app_token", "")
        self.table_id = cfg.get("table_id", "")
        self.work = work
        self._tok = None
        self._tok_exp = 0

    def _token(self):
        if self._tok and time.time() < self._tok_exp - 120:
            return self._tok
        r = requests.post(self.base + "/open-apis/auth/v3/tenant_access_token/internal",
                          json={"app_id": self.app_id, "app_secret": self.app_secret}, timeout=30)
        r.raise_for_status()
        d = r.json()
        if d.get("code"):
            raise RuntimeError(f"飞书鉴权失败 {d.get('code')}: {d.get('msg')}")
        self._tok = d["tenant_access_token"]
        self._tok_exp = time.time() + int(d.get("expire", 7200))
        return self._tok

    def _h(self):
        return {"Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json; charset=utf-8"}

    @staticmethod
    def _txt(v):
        """把飞书单元格值规整成字符串(文本字段可能是 str / [{text:..}] / 数字 / 复选框bool)。"""
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            return "".join(FeishuSheet._txt(x) for x in v)
        if isinstance(v, dict):
            return str(v.get("text") or v.get("name") or v.get("value") or "")
        return str(v)

    def _recs_url(self):
        return f"{self.base}/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"

    def read_rows(self):
        out, page = [], None
        while True:
            params = {"page_size": 200}
            if page:
                params["page_token"] = page
            r = requests.get(self._recs_url(), headers=self._h(), params=params, timeout=30)
            r.raise_for_status()
            d = r.json()
            if d.get("code"):
                raise RuntimeError(f"飞书读表失败 {d.get('code')}: {d.get('msg')}")
            data = d.get("data") or {}
            for it in data.get("items") or []:
                f = it.get("fields") or {}
                def g(field):
                    return f.get(self.cols.get(field))
                out.append({"id": self._txt(g("id")).strip(),
                            "image_url": self._txt(g("image_url")).strip(),
                            "confirm": self._is_confirm(self._txt(g("confirm"))),
                            "status": self._txt(g("status")).strip(),
                            "_rownum": it.get("record_id")})   # 用 record_id 当行标识
            if data.get("has_more"):
                page = data.get("page_token")
            else:
                break
        return out

    def write_back(self, record_id, fields):
        body = {"fields": {}}
        for field, val in fields.items():
            name = self.cols.get(field)
            if name:
                body["fields"][name] = val
        if not body["fields"] or not record_id:
            return
        requests.put(f"{self._recs_url()}/{record_id}", headers=self._h(),
                     json=body, timeout=30).raise_for_status()


# ---------------- 本地 xlsx（测试/无网时用） ----------------
class XlsxSheet(_Base):
    def __init__(self, cfg, cols, confirm_values):
        super().__init__(cols, confirm_values)
        self.path = cfg["path"]
        self._hdr_idx = {}

    def _load(self):
        from openpyxl import load_workbook
        wb = load_workbook(self.path)
        return wb, wb.active

    def read_rows(self):
        wb, ws = self._load()
        header = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
        self._hdr_idx = {name: i for i, name in enumerate(header)}
        out = []
        for ri in range(2, ws.max_row + 1):
            def g(field):
                j = self._hdr_idx.get(self.cols.get(field))
                return ws.cell(ri, j + 1).value if j is not None else None
            oid = g("id")
            if oid in (None, ""):
                continue
            out.append({"id": str(oid).strip(),
                        "image_url": str(g("image_url") or "").strip(),
                        "confirm": self._is_confirm(g("confirm")),
                        "status": str(g("status") or "").strip(),
                        "_rownum": ri})
        wb.close()
        return out

    def write_back(self, rownum, fields):
        wb, ws = self._load()
        for field, val in fields.items():
            j = self._hdr_idx.get(self.cols.get(field))
            if j is not None:
                ws.cell(rownum, j + 1).value = val
        wb.save(self.path)
        wb.close()


def make_backend(sheet_cfg, work="./_pilot_work"):
    cols = sheet_cfg["columns"]
    cv = sheet_cfg.get("confirm_values", ["是", "确认", "1", "true", "yes"])
    backend = sheet_cfg.get("backend", "dingtalk")
    if backend == "dingtalk":
        return DingTalkSheet(sheet_cfg["dingtalk"], cols, cv, work)
    if backend == "feishu":
        return FeishuSheet(sheet_cfg["feishu"], cols, cv, work)
    if backend == "wps":
        return WPSSheet(sheet_cfg["wps"], cols, cv, work)
    if backend == "xlsx":
        return XlsxSheet(sheet_cfg["xlsx"], cols, cv)
    raise ValueError(f"未知 sheet.backend: {backend}")

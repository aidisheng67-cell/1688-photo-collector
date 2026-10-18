"""配置加载与环境变量覆盖。

优先级：环境变量 > config.yaml > 代码默认值。
这样本地可以继续用 config.yaml，CI / Docker / 服务器则只注入环境变量，
密钥不需要写进任何文件。
"""
import copy
import os
import re

import yaml

# 环境变量 -> config 中的路径。只覆盖存在值的变量。
ENV_MAP = {
    "ONEBOUND_BASE_URL": ("api", "base_url"),
    "ONEBOUND_API_KEY": ("api", "key"),
    "ONEBOUND_API_SECRET": ("api", "secret"),
    "DINGTALK_APP_KEY": ("sheet", "dingtalk", "app_key"),
    "DINGTALK_APP_SECRET": ("sheet", "dingtalk", "app_secret"),
    "DINGTALK_WORKBOOK_ID": ("sheet", "dingtalk", "workbook_id"),
    "DINGTALK_SHEET_ID": ("sheet", "dingtalk", "sheet_id"),
    "DINGTALK_OPERATOR_ID": ("sheet", "dingtalk", "operator_id"),
    "FEISHU_APP_ID": ("sheet", "feishu", "app_id"),
    "FEISHU_APP_SECRET": ("sheet", "feishu", "app_secret"),
    "FEISHU_APP_TOKEN": ("sheet", "feishu", "app_token"),
    "FEISHU_TABLE_ID": ("sheet", "feishu", "table_id"),
    "WPS_APP_ID": ("sheet", "wps", "app_id"),
    "WPS_APP_SECRET": ("sheet", "wps", "app_secret"),
    "WPS_ACCESS_TOKEN": ("sheet", "wps", "access_token"),
    "WPS_FILE_TOKEN": ("sheet", "wps", "file_token"),
    "COLLECTOR_OUTPUT": ("paths", "output"),
    "COLLECTOR_WORK": ("paths", "work"),
    "COLLECTOR_CACHE": ("paths", "cache"),
    "COLLECTOR_LOG": ("paths", "log"),
    "COLLECTOR_REVIEW": ("paths", "review"),
}

SECRET_KEYS = {
    "key", "secret", "app_key", "app_secret", "access_token",
    "tenant_access_token", "token", "password", "operator_id",
}

_SECRET_QUERY = re.compile(
    r"(?i)\b(key|secret|app_secret|access_token|tenant_access_token|token|password)"
    r"=([^&\s\"']+)"
)


def _set(cfg, keys, value):
    cur = cfg
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[keys[-1]] = value


def load_config(path=None):
    """读取 YAML，并用环境变量覆盖敏感项。文件不存在时返回仅含环境变量的配置。"""
    path = path or os.environ.get("COLLECTOR_CONFIG", "config.yaml")
    cfg = {}
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    for env, keys in ENV_MAP.items():
        value = os.environ.get(env)
        if value not in (None, ""):
            _set(cfg, keys, value)
    return cfg


def redact_text(text, secrets=()):
    """把 URL/异常文本里的密钥和调用方传入的真实密钥替换为 ***。"""
    out = str(text)
    for s in secrets:
        if s and len(str(s)) >= 6:
            out = out.replace(str(s), "***")
    return _SECRET_QUERY.sub(r"\1=***", out)


def redact_config(cfg):
    """返回脱敏后的配置副本，可安全写日志或诊断导出。"""
    out = copy.deepcopy(cfg)
    for k, v in list(out.items()):
        if isinstance(v, dict):
            out[k] = redact_config(v)
        elif str(k).lower() in SECRET_KEYS and v not in (None, ""):
            out[k] = "***"
    return out


def strip_secrets(cfg):
    """返回去掉敏感字段的配置副本，供默认写盘使用。"""
    out = copy.deepcopy(cfg)
    for k, v in list(out.items()):
        if isinstance(v, dict):
            out[k] = strip_secrets(v)
        elif str(k).lower() in SECRET_KEYS:
            out.pop(k, None)
    return out


def save_config(cfg, path, persist_secrets=False):
    """保存配置。默认不落盘密钥；显式设置 COLLECTOR_PERSIST_SECRETS=1 才保留。"""
    import os

    persist = persist_secrets or os.environ.get("COLLECTOR_PERSIST_SECRETS") == "1"
    out = copy.deepcopy(cfg) if persist else strip_secrets(cfg)
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, allow_unicode=True, sort_keys=False)

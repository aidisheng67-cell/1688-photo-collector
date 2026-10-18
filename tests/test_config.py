import yaml

from config import load_config, redact_config, redact_text, save_config, strip_secrets


def test_env_overrides_file(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "api:\n  key: file-key\n  secret: file-secret\n  qps: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ONEBOUND_API_KEY", "env-key")
    monkeypatch.setenv("ONEBOUND_API_SECRET", "env-secret")
    monkeypatch.setenv("COLLECTOR_OUTPUT", str(tmp_path / "out"))

    cfg = load_config(str(cfg_path))

    assert cfg["api"]["key"] == "env-key"
    assert cfg["api"]["secret"] == "env-secret"
    assert cfg["api"]["qps"] == 2
    assert cfg["paths"]["output"] == str(tmp_path / "out")


def test_env_creates_nested_dict(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("sheet:\n  backend: xlsx\n", encoding="utf-8")
    monkeypatch.setenv("DINGTALK_APP_KEY", "ding-key")

    cfg = load_config(str(cfg_path))

    assert cfg["sheet"]["dingtalk"]["app_key"] == "ding-key"
    assert cfg["sheet"]["backend"] == "xlsx"


def test_redact_text_masks_query_and_explicit_secrets():
    text = "https://api.example.com/x?key=abc123&secret=def456&page=1 token=xyz"
    out = redact_text(text, secrets=("abc123", "def456"))
    assert "abc123" not in out
    assert "def456" not in out
    assert "xyz" not in out
    assert "page=1" in out


def test_redact_config_keeps_shape():
    cfg = {"api": {"key": "k", "secret": "s", "qps": 3},
           "sheet": {"dingtalk": {"app_key": "a", "workbook_id": "w"}}}
    out = redact_config(cfg)
    assert out["api"]["key"] == "***"
    assert out["api"]["secret"] == "***"
    assert out["api"]["qps"] == 3
    assert out["sheet"]["dingtalk"]["app_key"] == "***"
    assert out["sheet"]["dingtalk"]["workbook_id"] == "w"


def test_save_config_strips_secrets_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("COLLECTOR_PERSIST_SECRETS", raising=False)
    path = tmp_path / "saved.yaml"
    cfg = {"api": {"key": "k", "secret": "s", "qps": 3}, "paths": {"work": "./w"}}
    save_config(cfg, str(path))
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "key" not in saved["api"]
    assert "secret" not in saved["api"]
    assert saved["api"]["qps"] == 3
    assert "key" not in strip_secrets(cfg)["api"]


def test_save_config_can_persist_when_explicitly_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLECTOR_PERSIST_SECRETS", "1")
    path = tmp_path / "saved.yaml"
    save_config({"api": {"key": "k", "secret": "s"}}, str(path))
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["api"]["key"] == "k"
    assert saved["api"]["secret"] == "s"

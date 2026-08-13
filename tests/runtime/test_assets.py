from pathlib import Path

from conclave.runtime.assets import get_asset_root


def test_get_asset_root_uses_env_override(tmp_path, monkeypatch):
    asset_root = tmp_path / "assets"
    (asset_root / "static").mkdir(parents=True)
    (asset_root / "conclave-ui.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_ASSET_DIR", str(asset_root))

    assert get_asset_root() == asset_root.resolve()


def test_get_asset_root_finds_packaged_assets(monkeypatch):
    monkeypatch.delenv("CONCLAVE_ASSET_DIR", raising=False)

    root = get_asset_root()

    assert (root / "conclave-ui.html").is_file()
    assert (root / "static" / "openapi.json").is_file()
    assert root.parts[-3:] == ("src", "conclave", "assets")

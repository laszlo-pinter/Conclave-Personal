"""R5 (conclave#35): `conclave web` haengt das Mensch-Token nur an lokale Adressen, nie an fremde Hosts."""

from types import SimpleNamespace

import pytest


@pytest.fixture
def opened(monkeypatch):
    import conclave.cli.main as main
    import conclave.runtime.api_token as api_token
    from conclave.cli.config import ConclaveConfig

    urls = []
    monkeypatch.setattr(main, "open_browser", lambda url: urls.append(url) or True)
    monkeypatch.setattr(api_token, "read_token", lambda: "cvh_geheim")
    monkeypatch.setattr(ConclaveConfig, "from_sources", classmethod(lambda cls, *a, **k: ConclaveConfig(port=8000)))
    return main, urls


@pytest.mark.parametrize("url", ["http://example.org", "https://example.org:8000/", "ftp://127.0.0.1:8000",
                                 "http://localhost.example.org:8000", "http://10.0.0.5:8000",
                                 "http://127.0.0.1.example.org/"])
def test_foreign_url_gets_no_token(opened, url):
    main, urls = opened
    assert main._run_web(SimpleNamespace(url=url)) == 0
    assert urls == [url]


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000", "http://localhost:8000/", "http://[::1]:8000",
                                 "http://127.0.0.1:8123"])         # desktop auf ausweichendem Port
def test_own_loopback_url_gets_the_token(opened, url):
    main, urls = opened
    main._run_web(SimpleNamespace(url=url))
    assert urls == [f"{url}#token=cvh_geheim"]


def test_default_url_gets_the_token(opened):
    main, urls = opened
    main._run_web(SimpleNamespace(url=None))
    assert urls == ["http://127.0.0.1:8000#token=cvh_geheim"]

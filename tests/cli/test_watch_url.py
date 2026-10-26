"""AP 7 / bandit B310: conclave-watch akzeptiert nur http(s)-URLs."""

from unittest.mock import patch

import pytest

from conclave.cli import watch


@pytest.mark.parametrize("url,ok", [
    ("http://localhost:8000", True),
    ("https://conclave.lan", True),
    ("file:///etc/passwd", False),
    ("ftp://host", False),
    ("localhost:8000", False),
    ("http://", False),
])
def test_is_http_url(url, ok):
    assert watch.is_http_url(url) is ok


def test_fetch_never_opens_non_http_urls():
    with patch("urllib.request.urlopen") as urlopen:
        assert watch.fetch_conversation("file:///etc", "c1") is None
    urlopen.assert_not_called()


def test_main_rejects_non_http_api(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["conclave-watch", "c1", "--api", "file:///etc"])
    with pytest.raises(SystemExit) as exc:
        watch.main()
    assert exc.value.code == 2
    assert "http(s)" in capsys.readouterr().err

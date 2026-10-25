import pytest

from app.downloader import DownloadError, validate_url


@pytest.mark.parametrize("url", ["", "not a url", "ftp://example.com/a.mp3", "file:///tmp/a.mp3"])
def test_rejects_non_http_urls(url):
    with pytest.raises(DownloadError):
        validate_url(url, block_private=False)


@pytest.mark.parametrize("url", ["http://127.0.0.1/a", "http://localhost:8000/", "http://10.0.0.5/x", "http://192.168.1.1/"])
def test_blocks_private_hosts(url):
    with pytest.raises(DownloadError):
        validate_url(url, block_private=True)


def test_allows_private_hosts_when_disabled():
    assert validate_url("http://127.0.0.1/a", block_private=False) == "http://127.0.0.1/a"


def test_strips_whitespace():
    assert validate_url("  https://example.com/x  ", block_private=False) == "https://example.com/x"

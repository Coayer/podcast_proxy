import pytest
from app.utils import check_hostname, check_file_mime


def test_check_hostname_valid():
    check_hostname("https://www.google.com")


def test_check_hostname_invalid():
    with pytest.raises(ValueError):
        check_hostname("http://localhost")


def test_check_file_mime_valid():
    check_file_mime(b"<?xml version='1.0' encoding='UTF-8'?>", {"text/xml"})


def test_check_file_mime_invalid():
    with pytest.raises(ValueError):
        check_file_mime(b"GIF89a", {"application/xml"})

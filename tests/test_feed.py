from unittest.mock import Mock, patch
from pathlib import Path
import pytest
import requests
from lxml import etree
from app.feed.routes import (
    fetch_rss_feed,
    rewrite_rss_enclosure_urls,
    rewrite_youtube_feed,
    XML_NAMESPACES,
)

resources = Path(__file__).parent / "resources"

def test_proxy_feed_success(client):
    with patch('app.feed.routes.fetch_rss_feed') as mock_fetch:
        with patch('app.feed.routes.rewrite_rss_enclosure_urls') as mock_rewrite:

            mock_fetch.return_value = 'some feed content'
            mock_rewrite.return_value = b'<xml>rewritten feed</xml>'

            response = client.get('/feed/example.com/rss')

            assert response.status_code == 200
            assert response.data == b'<?xml version="1.0" encoding="UTF-8"?>\n<xml>rewritten feed</xml>'
            mock_fetch.assert_called_once_with('https://example.com/rss')
            mock_rewrite.assert_called_once_with('some feed content', 'https://localhost/feed/example.com/rss')

def test_proxy_feed_fetch_failure(client):
    with patch('app.feed.routes.fetch_rss_feed') as mock_fetch:
        mock_fetch.return_value = None

        response = client.get('/feed/example.com/rss')

        assert response.status_code == 500
        assert response.data == b'Failed to fetch feed'

def test_proxy_feed_rewrite_failure(client):
    with patch('app.feed.routes.fetch_rss_feed') as mock_fetch:
        with patch('app.feed.routes.rewrite_rss_enclosure_urls') as mock_rewrite:

            mock_fetch.return_value = 'some feed content'
            mock_rewrite.return_value = None

            response = client.get('/feed/example.com/rss')

            assert response.status_code == 500
            assert response.data == b'Failed to rewrite feed'

SAMPLE_RSS = '''<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"
    xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <atom:link href="https://original.com/rss" rel="self" type="application/rss+xml"/>
    <title>Test Podcast</title>
    <link>https://original.com</link>
    <itunes:new-feed-url>https://original.com/new-rss</itunes:new-feed-url>
    <item>
      <title>Episode 1</title>
      <enclosure url="https://cdn.original.com/ep1.mp3" type="audio/mpeg" length="1234"/>
    </item>
  </channel>
</rss>'''


def test_rewrite_rss_rewrites_atom_self_link(app):
    with app.test_request_context():
        result = rewrite_rss_enclosure_urls(SAMPLE_RSS, 'https://proxy.test/feed/original.com/rss')
        root = etree.fromstring(result)
        atom_self = root.find('channel/atom:link[@rel="self"]', namespaces=XML_NAMESPACES)
        assert atom_self.get("href") == "https://proxy.test/feed/original.com/rss"


def test_rewrite_rss_removes_itunes_new_feed_url(app):
    with app.test_request_context():
        result = rewrite_rss_enclosure_urls(SAMPLE_RSS, 'https://proxy.test/feed/original.com/rss')
        root = etree.fromstring(result)
        assert root.find('channel/itunes:new-feed-url', namespaces=XML_NAMESPACES) is None


def test_rewrite_rss_rewrites_channel_link(app):
    with app.test_request_context():
        result = rewrite_rss_enclosure_urls(SAMPLE_RSS, 'https://proxy.test/feed/original.com/rss')
        root = etree.fromstring(result)
        link = root.findtext('channel/link')
        assert link == "https://proxy.test/feed/original.com/rss"


def test_rewrite_rss_still_rewrites_enclosures(app):
    with app.test_request_context():
        result = rewrite_rss_enclosure_urls(SAMPLE_RSS, 'https://proxy.test/feed/original.com/rss')
        root = etree.fromstring(result)
        enclosure = root.find('channel/item/enclosure')
        assert 'cdn.original.com' not in enclosure.get("url")
        assert '/stream/' in enclosure.get("url")


def test_rewrite_youtube_feed(app):
    with app.test_request_context():
        with open(resources / "youtube_feed.xml", "r") as f:
            youtube_feed_content = f.read()
        rewritten_feed = rewrite_youtube_feed(youtube_feed_content)
        assert b'<title>Test Channel</title>' in rewritten_feed
        assert b'<description>Podcast feed for Test Channel</description>' in rewritten_feed
        assert b'<itunes:author>Test Author</itunes:author>' in rewritten_feed
        assert b'<title>Test Video Title</title>' in rewritten_feed
        assert b'<description>Test video description.</description>' in rewritten_feed


FEED_WITH_ENCLOSURE_LESS_ITEM = '''<rss version="2.0">
  <channel>
    <title>Test Podcast</title>
    <item><title>Show notes, no audio</title></item>
    <item><title>Blank enclosure</title><enclosure url="" type="audio/mpeg"/></item>
    <item><title>Real ep</title><enclosure url="https://cdn.original.com/ep2.mp3"/></item>
  </channel>
</rss>'''


def test_rewrite_rss_skips_items_without_enclosure(app):
    """One media-less item must not take down the entire feed"""
    with app.test_request_context():
        result = rewrite_rss_enclosure_urls(
            FEED_WITH_ENCLOSURE_LESS_ITEM, 'https://proxy.test/feed/original.com/rss'
        )

        assert result is not None
        root = etree.fromstring(result)
        assert len(root.findall('channel/item')) == 3

        enclosures = root.findall('channel/item/enclosure')
        assert enclosures[0].get("url") == ""  # blank left untouched
        assert '/stream/' in enclosures[1].get("url")


def test_rewrite_youtube_feed_with_no_videos(app):
    """A channel that has never published still produces a valid feed"""
    empty_channel = '''<feed xmlns="http://www.w3.org/2005/Atom">
      <title>Empty Channel</title>
      <link rel="alternate" href="https://youtube.com/c/empty"/>
      <author><name>Nobody</name></author>
    </feed>'''

    with app.test_request_context():
        result = rewrite_youtube_feed(empty_channel)

        assert result is not None
        root = etree.fromstring(result)
        assert root.findtext('channel/title') == 'Empty Channel'
        assert root.findall('channel/item') == []


def test_fetch_rss_feed_rejects_non_xml_content():
    """An HTML error page served where XML was expected must not become a feed"""
    response = Mock(encoding='utf-8')
    response.raise_for_status.return_value = None
    response.iter_content.return_value = iter([b'<html><body>404 Not Found</body></html>'])

    with patch('app.feed.routes.safe_get', return_value=response):
        assert fetch_rss_feed('https://example.com/rss') is None


def test_fetch_rss_feed_refuses_oversized_feed():
    """A hostile feed URL must not be able to exhaust memory.

    The payload is well-formed XML that would sail through the MIME check, so only
    the size cap can reject it.
    """
    padding = b'<item><title>' + b'p' * 8000 + b'</title></item>'
    oversized = iter(
        [b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>']
        + [padding] * 1500  # ~12MB, comfortably over the 10MB cap
    )

    response = Mock(encoding='utf-8')
    response.raise_for_status.return_value = None
    response.iter_content.return_value = oversized

    with patch('app.feed.routes.safe_get', return_value=response):
        assert fetch_rss_feed('https://example.com/rss') is None


def test_fetch_rss_feed_handles_request_exception():
    with patch(
        'app.feed.routes.safe_get', side_effect=requests.RequestException("boom")
    ):
        assert fetch_rss_feed('https://example.com/rss') is None


def test_fetch_rss_feed_rejects_unsafe_host():
    """check_hostname failures are swallowed into None, not raised"""
    assert fetch_rss_feed('http://127.0.0.1/rss') is None


def test_proxy_feed_unresolvable_host_returns_clean_500(client):
    """A DNS failure must surface as the handled error, not a raw traceback"""
    response = client.get('/feed/this-host-does-not-exist-xyzzy.invalid/rss')

    assert response.status_code == 500
    assert response.data == b'Failed to fetch feed'


def test_proxy_feed_youtube_path_builds_channel_feed_url(client):
    """/feed/youtube/<id> maps to the YouTube channel feed endpoint"""
    with patch('app.feed.routes.fetch_rss_feed') as mock_fetch:
        with patch('app.feed.routes.rewrite_youtube_feed') as mock_rewrite:
            mock_fetch.return_value = 'yt feed content'
            mock_rewrite.return_value = b'<xml>yt</xml>'

            response = client.get('/feed/youtube/UC123abc')

            assert response.status_code == 200
            mock_fetch.assert_called_once_with(
                'https://www.youtube.com/feeds/videos.xml?channel_id=UC123abc'
            )
            mock_rewrite.assert_called_once_with('yt feed content')
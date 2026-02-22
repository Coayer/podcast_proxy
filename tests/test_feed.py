from unittest.mock import patch
from pathlib import Path
from lxml import etree
from app.feed.routes import rewrite_rss_enclosure_urls, rewrite_youtube_feed, XML_NAMESPACES

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
from unittest.mock import patch
from pathlib import Path
from app.feed.routes import rewrite_youtube_feed

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
            mock_rewrite.assert_called_once_with('some feed content')

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
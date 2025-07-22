from unittest.mock import patch
import base64


def test_proxy_media_generic_stream(client):
    with patch("app.stream.routes.generic_stream") as mock_generic_stream:
        mock_generic_stream.return_value = "generic stream success"
        url = base64.urlsafe_b64encode(b"https://example.com/audio.mp3").decode()
        response = client.get(f"/stream/{url}")
        assert response.status_code == 200
        assert response.data == b"generic stream success"


def test_proxy_media_youtube_stream(client):
    with patch("app.stream.routes.youtube_stream") as mock_youtube_stream:
        mock_youtube_stream.return_value = "youtube stream success"
        url = base64.urlsafe_b64encode(
            b"https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        ).decode()
        response = client.get(f"/stream/{url}")
        assert response.status_code == 200
        assert response.data == b"youtube stream success"

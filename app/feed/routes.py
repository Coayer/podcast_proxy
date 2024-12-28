import requests
import base64
import logging
from app.utils import check_url, check_file
from flask import Response, url_for
from lxml import etree

from app.feed import bp

def fetch_rss_feed(feed_url):
    """Get RSS feed XML"""
    try:
        check_url(feed_url)
        response = requests.get(feed_url)
        response.raise_for_status()

        rss_mime_types = {"application/xml", "application/rss+xml", "text/xml"}
        check_file(response.content, rss_mime_types, 50000000)

        return response.text
    except requests.RequestException as e:
        logging.error(f"Error fetching feed: {e}")
        return None
    except ValueError as e:
        logging.error(f"Requested feed was unsafe: {e}")
        return None


def rewrite_enclosure_urls(feed_content):
    """Rewrite media enclosure URLs to proxy through server"""
    try:
        root = etree.fromstring(
            feed_content.encode(), parser=etree.XMLParser(strip_cdata=False)
        )

        for item in root.findall("./channel/item"):  # Episodes
            enclosure = item.find("enclosure")
            if enclosure is not None:
                original_url = enclosure.get("url")
                encoded_url = base64.urlsafe_b64encode(
                    original_url.encode()
                ).decode() # Encode string to file_bytes, b64 encode, then decode b64 file_bytes to string
                proxy_url = url_for(
                    "stream.proxy_media", encoded_url=encoded_url, _external=True
                )
                enclosure.set("url", proxy_url)

        return etree.tostring(root)
    except Exception as e:
        logging.error(f"Error rewriting feed: {e}")
        return None


@bp.route("/<path:feed_path>")
def proxy_feed(feed_path):
    original_feed_url = f"https://{feed_path}"

    logging.info(f"Rewriting episode URLs: {original_feed_url}")

    feed_content = fetch_rss_feed(original_feed_url)
    if not feed_content:
        return "Failed to fetch feed", 500

    rewritten_feed = rewrite_enclosure_urls(feed_content)
    if not rewritten_feed:
        return "Failed to rewrite feed", 500

    return Response(
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + rewritten_feed,  # Apple podcasts requires the XML declaration
        mimetype="application/rss+xml",
    )

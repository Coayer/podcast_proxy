import hashlib
from datetime import datetime

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

        for item in root.findall("channel/item"):  # Episodes
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


def rewrite_youtube(feed_content):
    # try:
    root = etree.fromstring(feed_content.encode(), parser=etree.XMLParser(strip_cdata=False, remove_blank_text=True))
    atom_namespace = {"atom": "http://www.w3.org/2005/Atom"}

    link = root.find('atom:link[@rel="alternate"]', namespaces=atom_namespace).get("href")
    title = root.findtext("atom:title", namespaces=atom_namespace)
    description = f"Podcast feed for {title}"
    author = root.findtext("atom:author/atom:name", namespaces=atom_namespace)

    rewritten_feed = etree.parse("./app/feed/rss_structure.xml")
    channel = rewritten_feed.find("channel")
    channel.find("title").text = title
    channel.find("description").text = description
    channel.find("atom:link", namespaces=atom_namespace).set("href", "http://127.0.0.1:5000/feed/youtube/UCGy7hYVpw7MsIgjJCTmuBBg")
    channel.find("link").text = link
    channel.find("itunes:author", namespaces={"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}).text = author

    for entry_element in root.findall("atom:entry", namespaces=atom_namespace):
        item = etree.Element("item")

        title = entry_element.findtext("atom:title", namespaces=atom_namespace)

        link = entry_element.find("atom:link[@rel='alternate']", namespaces=atom_namespace).get("href")

        description = entry_element.findtext("media:group/media:description", namespaces={'media': 'http://search.yahoo.com/mrss/'})

        pub_date = entry_element.findtext("atom:published", namespaces=atom_namespace)
        pub_date = datetime.fromisoformat(pub_date).strftime("%a, %d %b %Y %H:%M:%S +0000")

        # Create a new guid (you could use a hash of the ID or videoId as required)
        video_id = entry_element.findtext("yt:videoId", namespaces={'yt': 'http://www.youtube.com/xml/schemas/2015'})

        guid = etree.Element("guid", isPermaLink="false")
        guid.text = hashlib.sha256(video_id.encode('utf-8')).hexdigest()[:32]
        item.append(guid)

        title_element = etree.Element("title")
        title_element.text = title
        item.append(title_element)

        description_element = etree.Element("description")
        description_element.text = description
        item.append(description_element)

        pub_date_element = etree.Element("pubDate")
        pub_date_element.text = pub_date
        item.append(pub_date_element)

        link_element = etree.Element("link")
        link_element.text = link
        item.append(link_element)

        item.append(etree.Element("enclosure", length="0", type="audio/mp4", url=link))

        channel.append(item)

    return etree.tostring(rewritten_feed, pretty_print=True, xml_declaration=True)
    # except Exception as e:
    #     logging.error(f"Error rewriting YouTube channel feed: {e}")
    #     return None


@bp.route("/<path:feed_path>")
def proxy_feed(feed_path):
    youtube = feed_path.startswith("youtube/")
    if youtube:
        feed_path = f"www.youtube.com/feeds/videos.xml?channel_id={feed_path.split('/')[1]}"

    original_feed_url = f"https://{feed_path}"

    logging.info(f"Rewriting episode URLs: {original_feed_url}")

    feed_content = fetch_rss_feed(original_feed_url)
    if not feed_content:
        return "Failed to fetch feed", 500

    if youtube:
        rewritten_feed = rewrite_youtube(feed_content)
    else:
        rewritten_feed = rewrite_enclosure_urls(feed_content)

    if not rewritten_feed:
        return "Failed to rewrite feed", 500

    return Response(
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + rewritten_feed,  # Apple podcasts requires the XML declaration
        mimetype="application/rss+xml",
    )

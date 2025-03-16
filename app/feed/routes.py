import hashlib
import requests
import base64
import logging
from datetime import datetime
from app.utils import check_url, check_file_safety
from flask import Response, url_for
from lxml import etree

from app.feed import bp

XML_NAMESPACES = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "media": "http://search.yahoo.com/mrss/",
    "atom": "http://www.w3.org/2005/Atom"
}

def create_proxied_stream_url(original_url):
    """Create encoded URL to stream file at a given URL through the proxy server"""
    encoded_url = base64.urlsafe_b64encode(
        original_url.encode()
    ).decode()  # Encode string to file_bytes, b64 encode, then decode b64 file_bytes to string
    return url_for(
        "stream.proxy_media", encoded_url=encoded_url, _external=True, _scheme="https"
    )


def fetch_rss_feed(feed_url):
    """Get RSS feed XML"""
    try:
        check_url(feed_url)
        response = requests.get(feed_url)
        response.raise_for_status()

        rss_mime_types = {"application/xml", "application/rss+xml", "text/xml"}
        check_file_safety(response.content, rss_mime_types, 50000000)

        return response.text
    except requests.RequestException as e:
        logging.error(f"Error fetching feed: {e}")
        return None
    except ValueError as e:
        logging.error(f"Requested feed was unsafe: {e}")
        return None


def rewrite_rss_enclosure_urls(feed_content):
    """Rewrite media enclosure URLs to proxy through server's address"""
    try:
        root = etree.fromstring(
            feed_content.encode(), parser=etree.XMLParser(strip_cdata=False)
        )

        for item in root.findall("channel/item"):  # items = episodes
            enclosure = item.find("enclosure")
            proxied_url = create_proxied_stream_url(enclosure.get("url"))
            enclosure.set("url", proxied_url)

        return etree.tostring(root)
    except Exception as e:
        logging.error(f"Error rewriting feed: {e}")
        return None


def rewrite_youtube_feed(feed_content):
    """Create an RSS feed from a YouTube channel XML feed"""
    try:
        youtube_channel_feed = etree.fromstring(feed_content.encode(),
                                        parser=etree.XMLParser(strip_cdata=False, remove_blank_text=True))

        podcast_feed = etree.parse("./app/feed/feed_skeleton.xml")
        channel = podcast_feed.find("channel")  # will contain all episode objects in final RSS feed

        for entry in youtube_channel_feed.findall("atom:entry", namespaces=XML_NAMESPACES):
            channel.append(convert_yt_entry_to_rss_item(entry))

        latest_thumbnail = channel.find("item/itunes:image", namespaces=XML_NAMESPACES).get("href") # use latest video thumbnail as podcast image, otherwise need YT API
        convert_yt_channel_to_podcast_channel(youtube_channel_feed, channel, image_url=latest_thumbnail)

        return etree.tostring(podcast_feed, pretty_print=True)
    except Exception as e:
        logging.error(f"Error rewriting YouTube channel feed: {e}")
        return None


def convert_yt_channel_to_podcast_channel(youtube_feed, channel, image_url):
    """Convert YouTube XML channel metadata into RSS podcast metadata"""
    link = youtube_feed.find('atom:link[@rel="alternate"]', namespaces=XML_NAMESPACES).get("href")
    title = youtube_feed.findtext("atom:title", namespaces=XML_NAMESPACES)
    description = f"Podcast feed for {title}"
    author = youtube_feed.findtext("atom:author/atom:name", namespaces=XML_NAMESPACES)

    channel.find("title").text = title
    channel.find("description").text = description
    channel.find("atom:link", namespaces=XML_NAMESPACES).set("href", link)
    channel.find("link").text = link
    channel.find("itunes:author", namespaces=XML_NAMESPACES).text = author
    channel.find("itunes:image", namespaces=XML_NAMESPACES).set("href", image_url)

    return channel


def convert_yt_entry_to_rss_item(entry):
    """Convert a YouTube XML feed <entry> into an RSS <item>"""
    item = etree.Element("item")  # new item to populate

    title = entry.findtext("atom:title", namespaces=XML_NAMESPACES)
    link = entry.find("atom:link[@rel='alternate']", namespaces=XML_NAMESPACES).get("href")
    description = entry.findtext("media:group/media:description",
                                 namespaces=XML_NAMESPACES)

    pub_date = entry.findtext("atom:published", namespaces=XML_NAMESPACES)
    pub_date = datetime.fromisoformat(pub_date).strftime("%a, %d %b %Y %H:%M:%S +0000")

    def create_etree_element(element_name, element_text):
        element = etree.Element(element_name)
        element.text = element_text
        return element

    for name, text in [("title", title), ("description", description), ("pubDate", pub_date), ("link", link)]:
        item.append(create_etree_element(name, text))

    image_url = entry.find("media:group/media:thumbnail", namespaces=XML_NAMESPACES).get("url")
    item.append(etree.Element(f"{{{XML_NAMESPACES['itunes']}}}image", href=image_url))

    guid = etree.Element("guid", isPermaLink="false")
    video_id = entry.findtext("yt:videoId", namespaces={"yt": "http://www.youtube.com/xml/schemas/2015"})
    guid.text = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:32]
    item.append(guid)

    proxied_url = create_proxied_stream_url(link)
    item.append(etree.Element("enclosure", length="0", type="audio/mp4", url=proxied_url))

    return item


@bp.route("/<path:feed_path>")
def proxy_feed(feed_path):
    """Create a proxied RSS feed for a podcast or YouTube channel"""
    youtube = feed_path.startswith("youtube/")
    if youtube:
        feed_path = f"www.youtube.com/feeds/videos.xml?channel_id={feed_path.split('/')[1]}"

    original_feed_url = f"https://{feed_path}"

    logging.info(f"Creating feed: {original_feed_url}")

    feed_content = fetch_rss_feed(original_feed_url)
    if not feed_content:
        return "Failed to fetch feed", 500

    if youtube:
        rewritten_feed = rewrite_youtube_feed(feed_content)
    else:
        rewritten_feed = rewrite_rss_enclosure_urls(feed_content)

    if not rewritten_feed:
        return "Failed to rewrite feed", 500

    return Response(
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + rewritten_feed,  # Apple podcasts requires the XML declaration
        mimetype="application/rss+xml",
    )

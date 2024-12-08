import requests
import os
import base64
import logging
import magic
from flask import Flask, Response, request, url_for
from lxml import etree

# TODO santitation of URLs

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')

EXTERNAL_PROXY = os.getenv('EXTERNAL_PROXY')
logging.info(f'Using proxy server: {EXTERNAL_PROXY}')

app = Flask(__name__)

STREAM_MIME_TYPES = set([
    'audio/mpeg', 
    'audio/x-mpeg', 
    'audio/mp3', 
    'audio/wav', 
    'audio/ogg', 
    'application/octet-stream'
])

RSS_MIME_TYPES = set([
    'application/xml',
    'application/rss+xml',
    'text/xml'
])

def check_file(bytes, allowed_mime_types, max_size):
    detected_mime = magic.from_buffer(bytes[:2048], mime=True)
    
    if detected_mime not in allowed_mime_types:
        raise ValueError(f'Detected MIME type is not allowed: {detected_mime}')

    if len(bytes) > max_size:
        raise ValueError(f'File size exceeds maximum allowed limit: {len(bytes)/1000000}/{max_size/{1000000}}')

def fetch_rss_feed(feed_url):
    '''Get RSS feed XML'''
    try:
        response = requests.get(feed_url)   
        response.raise_for_status()

        check_file(response.content, RSS_MIME_TYPES, 50000000)

        return response.text
    except requests.RequestException as e:
        logging.error(f'Error fetching feed: {e}')
        return None
    except ValueError as e:
        logging.error(f'Requested feed was unsafe: {e}')

def rewrite_enclosure_urls(feed_content):
    '''Rewrite media enclosure URLs to proxy through server'''
    try:
        root = etree.fromstring(feed_content.encode(), parser=etree.XMLParser(strip_cdata=False))
        
        for item in root.findall('./channel/item'): # Episodes
            enclosure = item.find('enclosure')
            if enclosure is not None:
                original_url = enclosure.get('url')
                encoded_url = base64.urlsafe_b64encode(original_url.encode()).decode()  # Encode string to bytes, b64 encode, then decode b64 bytes to string
                proxy_url = url_for('proxy_media', encoded_url=encoded_url, _external=True)
                enclosure.set('url', proxy_url)
        
        return etree.tostring(root)
    except Exception as e:
        logging.error(f'Error rewriting feed: {e}')
        return None

@app.route('/feed/<path:feed_path>')
def proxy_feed(feed_path):
    original_feed_url = f'https://{feed_path}'

    logging.info(f'Rewriting episode URLs: {original_feed_url}')

    feed_content = fetch_rss_feed(original_feed_url)
    if not feed_content:
        return 'Failed to fetch feed', 500
    
    rewritten_feed = rewrite_enclosure_urls(feed_content)
    if not rewritten_feed:
        return 'Failed to rewrite feed', 500
    
    return Response(rewritten_feed, mimetype='application/rss+xml')

@app.route('/stream/<path:encoded_url>')
def proxy_media(encoded_url):    
    original_url = base64.urlsafe_b64decode(encoded_url.encode()).decode()

    logging.info(f'Streaming: {original_url}')

    # Cloudflare adds many other headers which can prevent the connection being accepted
    allowed_headers = set(['User-Agent', 'Accept-Encoding', 'Accept', 'Connection', 'Range', 'Icy-Metadata'])        
    headers = {header: value for header, value in request.headers.items() if header in allowed_headers}

    try:        
        media_response = requests.get(original_url, proxies={'https': EXTERNAL_PROXY}, headers=headers, allow_redirects=True, stream=True)
        media_response.raise_for_status()

        check_file(media_response.content, STREAM_MIME_TYPES, 500000000)

        return Response(
            media_response.iter_content(chunk_size=120000),
            status=media_response.status_code,
            headers=media_response.headers
        )
    except requests.exceptions.HTTPError as e:
        logging.error(f'HTTP error occurred: {e}')
        return 'Failed to stream from upstream server', e.response.status_code
    except ValueError as e:
        logging.error(f'Requested stream was unsafe: {e}')
    except Exception as e:
        logging.error(f'Error streaming media: {e}')
        return 'Failed...', 500
    
@app.route('/')
def root():
    return '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Podcast Proxy Usage</title>
    </head>
    <body>
        <p>
            Proxied podcasts can be added to clients by placing the original podcast RSS URL (with protocol omitted) after the <code>/feed/</code> path of the proxy server.
        </p>
        <p>
            For example, the podcast located at:
        </p>
        <pre><code>https://feeds.simplecast.com/LDNgBXht</code></pre>
        <p>
            Should be added to the podcast client as:
        </p>
        <pre><code id="proxy-url"></code></pre>

        <script>
            const hostname = window.location.hostname;
            const port = window.location.port;
            const rssPath = "/feed/feeds.simplecast.com/LDNgBXht";

            const proxyUrl = port 
                ? `https://${hostname}:${port}${rssPath}` 
                : `https://${hostname}${rssPath}`;

            document.getElementById("proxy-url").textContent = proxyUrl;
        </script>
    </body>
    </html>
    ''', 200

if __name__ == '__main__':
    app.run()

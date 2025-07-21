# podcast_proxy

A proxy server just for streaming podcasts! Combined with a VPN connected to another country, adverts can be served (or not) as if you were there!

The server can also turn YouTube channels into podcast feeds.

## Usage

### Hosting

```
version: '3.8'
services:
  webserver:
    image: ghcr.io/coayer/podcast_proxy:latest
    ports:
      - 8080:80
    environment:
      EXTERNAL_PROXY: "http://gluetun:8888"
```

#### Environment variables

`EXTERNAL_PROXY`: (Optional) Proxies streams through an additional HTTP proxy. For example, using [qdm12/gluetun](https://github.com/qdm12/gluetun) with the `HTTPPROXY` variable enabled, the podcast proxy server can stream podcasts through the VPN with other containers still using the host network.

`ENABLE_STREAMING_SAFETY_CHECK`: (Optional, defaults to `false`) When set to `true`, upstream responses will be checked against valid audio MIME file types. Reduces ability to stream arbitrary files (but making server publicly accessible is at your own risk).

### Clients

Proxied podcasts are added to clients by creating rewritten feed URLs.

These can be generated using the web UI at the server's root:

![image](web_ui.jpg)

The newly-generated feed URLs embed the existing upstream feed. This means the proxy server can be stateless.

Podcast feed URLs can also be manually created:

#### RSS feeds

RSS feed URLs are rewritten by placing the original podcast URL (with protocol omitted) after the `/feed/` route of the proxy server.

For example, the podcast:

`https://feeds.simplecast.com/LDNgBXht` 

Would be added to the client as:

`https://podcast-proxy.example.com/feed/feeds.simplecast.com/LDNgBXht`

This will rewrite the episode URLs from the upstream feed to instead be streamed via the `/stream/` route on the server (change `podcast-proxy.example.com` to your server's location).

#### YouTube channels

YouTube channel podcast feeds are created with the path:

`https://podcast-proxy.example.com/feed/youtube/CHANNEL_ID`

To get a YouTube channel's ID: 

Go to the YouTube channel page → Click ...more → Share channel → Copy channel ID

Streaming YouTube videos for the first time will have a slight delay while the audio file is downloaded from YouTube to the proxy server. Once the download is complete, playback will begin instantly on all subsequent plays while the video is cached.

Because the audio files are stored in the container's filesystem, restarting the proxy server will clear the episode cache. To create a persistent cache on the container host, use a volume mounted to `/cache`.

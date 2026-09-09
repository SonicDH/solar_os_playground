# RSS Reader

RSS Reader is an offline-first, text-only RSS 2.0 and Atom reader for SolarOS.
It combines subscribed feeds into one timeline while retaining per-feed views
and cached article text for disconnected reading.

## Features

- Aggregate and individual-feed views.
- Add and remove HTTPS RSS or Atom feeds on the device.
- BBC World News, Hackaday, and Hacker News starter subscriptions.
- Configurable retention of 1 to 50 posts per feed.
- Read/unread tracking and a per-feed "mark all read" action.
- Offline article cache with a separate body file for each post.
- Basic HTML and Markdown conversion for terminal reading.
- Image placeholders based on alt text or the source filename; images are not
  downloaded.
- Streamed, one-feed-at-a-time refreshes with bounded memory use.

Feed subscriptions are stored in `feeds.json`, lightweight article metadata in
`cache.json`, and article bodies below `articles/`, all beside the installed
script. A normal SD-card Playground installation uses:

```text
/sdcard/playground/python/rss/
```

Each feed receives its own stable folder under `articles/`. Old cached content
remains available when a refresh fails. Article bodies are capped at 12 KiB,
and files that age out of a feed's configured retention limit are removed.

## Controls

- Up/Down: move through posts.
- Page Up/Page Down: move five posts at a time.
- Enter or Right: open the selected article and mark it read.
- `r`: refresh all configured feeds.
- `f`: open the feed manager or change between aggregate and feed views.
- `m`: mark every cached post in the current individual feed as read.
- In the feed manager, `a` adds a feed and `x` removes one.
- In the feed manager, `+`/`-` changes retained posts per feed.
- Escape, Left, or `q`: go back or quit.

Removing a subscription leaves its already cached posts intact. The app does
not download linked web pages or images and cannot hand a link directly to the
graphical Web application.

## Requirements

RSS Reader requires SolarOS 4.8.4 or newer, Wi-Fi, and the Python and
Playground packages. It uses the streaming `solaros.http` API and the terminal
UI, so it does not require a graphical display.

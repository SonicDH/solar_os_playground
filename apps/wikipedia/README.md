# Wikipedia Reader

Wikipedia Reader is a text-first Wikipedia client for constrained SolarOS
devices. It uses Wikipedia's plain-text extract API for fast article loading
and fetches link data separately for in-app browsing.

## Features

- Search by article title and text.
- Open a random article.
- Follow internal Wikipedia links without leaving the app.
- Keep bookmarks and recently viewed articles.
- Cache up to 20 ordinary articles for quick repeat and offline reading.
- Keep selected articles in a separate, uncapped offline library.
- Choose a Wikipedia language edition.
- Clear disposable cache and recent history independently.
- Stream article extracts and link data to disk to bound memory use.
- Omit images, tables, and other web-page chrome.

Configuration, history, bookmarks, the article cache, and the offline library
are stored beside the installed script. Article identities include their
Wikipedia language, so saved copies from different editions can coexist. A normal SD-card Playground
installation uses:

```text
/sdcard/playground/python/wikipedia/
```

The 20-article cache has no time-to-live; it evicts older disposable articles
only when the count limit is exceeded. Articles marked for offline use are not
subject to that cap.

## Controls

- Up/Down or Page Up/Page Down: turn article pages or move through lists.
- Enter or `l`: list links in the current article.
- `s`: add or remove the current article as a bookmark.
- `o`: keep or remove the current article in the offline library.
- Escape or `q`: go back or quit.

The Settings screen changes the language, clears the disposable article cache,
or clears recent history. Clearing the cache preserves offline-kept articles;
clearing history preserves both cached and offline articles.

## Desktop offline-library builder

The companion `build_offline_cache.py` utility in this project's desktop tools
accepts a UTF-8 file containing one Wikipedia article URL per line:

```text
python build_offline_cache.py links.txt --output wikipedia-offline
```

Blank lines and lines beginning with `#` are ignored. All URLs in one run must
use the same Wikipedia language. Copy the generated `cache/`, `offline.json`,
and `config.json` into the installed Wikipedia Reader directory.

## Requirements

Wikipedia Reader requires SolarOS 4.8.4 or newer, Wi-Fi, and the Python and
Playground packages. Already cached and offline-kept articles remain readable
without a connection. The app uses the package-gated synchronous and streaming
`solaros.http` APIs and the terminal UI, so it does not require a graphical
display.

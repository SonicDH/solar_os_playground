# OPDS Browser

OPDS Browser is a text-first OPDS 1.x catalog client and book downloader for
SolarOS. It works with Kavita and conventional OPDS repositories while leaving
book reading to SolarOS Reader.

## Features

- Configure and browse multiple OPDS servers.
- Kavita base URL and auth-key setup, full OPDS URLs, and HTTP Basic auth.
- Follow navigation feeds and paginated catalog results.
- Search servers that advertise an OpenSearch endpoint.
- Keep a single offline To Read list across all configured servers.
- Stream downloads to `/Books` with filesystem-safe filenames.
- Show explanatory progress stages while downloading and parsing.
- Reuse parsed pages from a short-lived eight-page cache.
- Cooperatively precache nearby catalog pages without freezing input.
- Filter downloads to EPUB, plain text, and Markdown formats supported by
  SolarOS Reader.
- Open a selected downloaded book directly in its registered reader app.

Server profiles and credentials are stored in `servers.json` beside the
installed script. To Read and download-history records are stored there as
well. A normal SD-card Playground installation uses:

```text
/sdcard/playground/python/opds/
```

Credentials are plain text. Do not distribute `servers.json` in a support
bundle or copied installation. Downloaded books remain in `/Books` when the app
is upgraded or removed.

## Controls

- Up/Down: move through lists.
- Page Up/Page Down: move by a visible page.
- Enter: open a server, feed, book, or action.
- `/`: search the active server when it advertises OpenSearch.
- `s`: add or remove a compatible book from To Read.
- In Manage Servers, `a` adds and `x` removes a server.
- Escape or `q`: go back or quit.
- In Downloaded, `Enter` opens the selected local book in SolarOS Reader.

Downloaded books can also be opened from a shell with:

```text
reader /Books/book-name.epub
```


## Limits

Catalog pages are capped at 512 KiB, descriptions at 2 KiB per To Read item,
and individual downloads at 64 MiB. Covers, PDF display, and
reading-progress synchronization are intentionally omitted.

## Requirements

OPDS Browser requires SolarOS 4.13.6 or newer, Wi-Fi, and the Python and
Playground packages. It uses the streaming `solaros.http` and app handoff APIs
and the terminal UI, so it does not require a graphical display or an SD card.

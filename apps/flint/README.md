# Flint for SolarOS

Flint is an offline Markdown notebook and personal knowledge base for SolarOS.
It keeps notes as ordinary files, adds Obsidian-style wiki links and backlinks,
and treats daily notes as one part of a general-purpose vault.

## Features

- Folder-based Markdown vault
- `[[Wiki links]]`, `[[Note|aliases]]`, and `[[Note#Heading]]`
- Link hopping and creation of missing linked notes
- Backlinks
- Daily notes with an editable template
- Tags, search, recent notes, and favorites
- Graphical vault and folder browser
- Full-document Markdown editor with a cursor-centered viewport
- Note creation, deletion, renaming, and moving
- Folder creation, renaming, and safe deletion
- Automatic exact-link updates when a note is renamed
- Explicit, progress-reporting refresh of all known indexed notes
- Command-line import for notes copied onto the device outside Flint
- Direct opening of an existing Markdown or text file supplied as an argument
- Atomic note, configuration, and index writes
- UTF-8-aware 32 KiB editor limit
- Safe recovery when an index update or refresh is interrupted
- Independent indexes for multiple configured vaults
- Lists reopen at the previous position after closing a note
- No image decoding or table layout

## Installation and launch

Install Flint through Playground, or copy this directory to `/apps/flint` and
add the included alias line to `/.shell/alias`.

```text
flint
flint /notes/vault/Projects/SolarOS.md
flint --add-file /downloads/SolarOS.md
flint --add-list /downloads/flint-paths.txt
```

The second form opens a Markdown or text file directly. Press `B` from its
reading screen to enter the vault browser. While actively editing, use
`Ctrl+B` instead, because an ordinary `B` is inserted into the note.

`--add-file` adds a file to the vault. A file already under the configured
vault root is indexed in place. A file elsewhere is copied into the vault root
with a safe, unique filename. Supported files are `.md`, `.markdown`, and
`.txt`, up to Flint's normal 32 KiB note limit.

`--add-list` reads absolute note paths from a newline-delimited text file and
adds them in one Python session. Empty lines and lines beginning with `#` are
ignored. This is useful in SolarOS shell scripts, because launching a
foreground application ends the remainder of the script.

## Main areas

- **Today's note** opens or creates `Daily/YYYY-MM-DD.md` using the configured
  template.
- **Browse vault** navigates folders and notes.
- **Recent notes** and **Favorites** provide quick access.
- **Search** checks indexed metadata and then scans one note body at a time.
- **Tags** groups indexed notes by hashtag.
- **Refresh index** scans the vault recursively, adds supported files that were
  copied in outside Flint, refreshes note metadata, and removes entries for
  deleted files.

## Reader controls

- `Up` / `Down`: scroll
- `Page Up` / `Page Down`: move one page
- `E`: edit
- `L`: list and follow wiki links
- `K`: show backlinks
- `F`: toggle favorite
- `A`: show every note action, including rename, move, and delete
- `B`: open the vault browser from the current note's folder
- `Esc`: return to the previous screen

## Vault browser controls

- `Enter`: open the highlighted folder or note
- `N`: create a note in the current folder
- `F`: create a subfolder
- `M`: rename the highlighted folder
- `D`: delete the highlighted note or folder after confirmation
- `R`: refresh the saved index
- `Esc`: move to the parent folder or leave the browser

Deleting a folder moves every indexed note beneath it to the vault-root
`orphaned notes` folder before removing it. Filename collisions receive a
numbered filename. If an unindexed file prevents the now-empty folder from
being removed, Flint leaves that folder in place and reports the problem.

## Editor controls

- Printable keys: insert text at the cursor
- `Enter`: insert a newline
- Arrow keys: move the cursor
- `Page Up` / `Page Down`: move several lines
- `Home` / `End`: move to the beginning or end of the current line
- `Backspace` / `Delete`: remove text
- `Tab`: insert four spaces
- `Ctrl+S`: save and return to reading mode
- `Ctrl+B`: save or discard changes and enter the vault browser
- `Esc`: return to reading mode, prompting if the note changed

## Storage and compatibility

The default vault is `/notes/vault`. Its contents are normal `.md`,
`.markdown`, and `.txt` files that can also be opened by SolarOS Reader or
Writer and copied to a desktop Markdown application.

Flint's rebuildable indexes and settings live separately in `/.flint`. Each
configured vault has its own index, so switching vaults cannot mix their notes.
The default vault retains the compatible `index.json` filename. An index
contains titles, paths, tags, outgoing links, previews, favorites, and recent
paths; it is not the authoritative copy of any note.

Flint recognizes common Markdown headings, paragraphs, lists, block quotes,
code fences, rules, inline links, emphasis, and wiki links. Images are replaced
with a short “Image omitted” line. Tables remain readable source text rather
than being laid out as grids. Plugin syntax, Canvas, Dataview, embedded web
content, and graph visualization are not supported.

## Resource limits

- Up to 512 indexed notes
- Up to 32 KiB per note
- Up to 32 KiB per editable document
- Up to 16 indexed tags and 32 outgoing wiki-link targets per note

Only the current note is loaded for reading or editing, and full-text search
opens one note at a time. The browser is populated from Flint's saved index;
use **Refresh index** after transferring files through Files, FTP, or another
app. Refresh discovers supported files recursively, up to the 512-note index
limit. These limits keep memory use predictable on ESP32 devices.

## Privacy

Flint data is stored as plaintext Markdown. The app intentionally does not
offer a cosmetic PIN screen or claim that the vault is encrypted.

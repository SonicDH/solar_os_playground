# Flint TUI for SolarOS

Flint TUI is the text-interface edition of Flint, an offline Markdown notebook
and personal knowledge base for SolarOS. The original graphical edition remains
in the separate `flint` package.

Both editions use the same default vault (`/notes/vault`), configuration, and
per-vault indexes (`/.flint`), so notes can be opened in either one without
conversion and switching vaults cannot mix their note lists.

## Features

- Folder-based Markdown vault
- Full-document, line-based text editor
- `[[Wiki links]]`, aliases, heading links, and backlinks
- Link hopping and creation of missing linked notes
- Daily notes with an editable template
- Tags, full-text search, recent notes, and favorites
- Note creation, deletion, renaming, and moving
- Folder creation, renaming, and safe deletion
- Exact wiki-link updates when a note is renamed
- Recursive vault refresh that discovers added files and removes deleted files
- Import and in-place indexing of files copied onto the device
- Atomic note, configuration, and index writes
- UTF-8-aware 32 KiB editor limit
- Safe recovery when an index update or refresh is interrupted
- Lists reopen at the previous position after closing a note
- Text rendering for headings, lists, quotes, code, links, and emphasis
- Image placeholders and plain-text tables; no image decoding

## Launch and import

```text
flint-tui
flint-tui /notes/vault/Projects/SolarOS.md
flint-tui --add-file /downloads/SolarOS.md
flint-tui --add-list /downloads/flint-paths.txt
```

Files already inside the configured vault are indexed in place. Files outside
it are copied to the vault root using a safe, unique filename. Flint accepts
`.md`, `.markdown`, and `.txt` notes up to 32 KiB.

`--add-list` reads newline-delimited absolute paths from a text file and adds
them in one Python session. Empty lines and `#` comment lines are ignored.

## Reader controls

- `Up` / `Down`: scroll one row
- `Page Up` / `Page Down`: scroll one page
- `E`: edit the complete document
- `L`: list and follow wiki links
- `K`: show backlinks
- `F`: toggle favorite
- `A`: show all note actions
- `B`: open the vault browser
- `Esc`: return to the previous screen

## Editor controls

- Printable keys: insert into the active line
- `Enter`: split the active line at the cursor
- `Backspace` at the start of a line: join it to the preceding line
- `Delete` at the end of a line: join it to the following line
- Arrow keys: move within and between lines
- `Page Up` / `Page Down`: move several lines
- `Home` / `End`: move to the start or end of the active line
- `Tab`: insert four spaces
- `Ctrl+S`: save and return to the reader
- `Ctrl+B`: save or discard changes and open the vault browser
- `Esc`: return to the reader, prompting if the document changed

The editing buffer is a list of physical Markdown lines. Normal typing copies
only the active line. The complete document is joined only when it is saved or
when the editor must return its contents.

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
numbered filename. A folder containing unindexed files is left in place if it
cannot safely be emptied.

## Storage

The vault browser is populated from Flint's saved index. Use **Refresh index**
after transferring files through Files, FTP, or another app; refresh recursively
discovers supported files, updates note metadata, and removes deleted files from
the index. The index supports up to 512 notes. Notes created by either Flint
edition are indexed automatically. The `--add-file` and `--add-list` commands
remain available for direct imports.

Flint stores plaintext Markdown and does not claim to encrypt the vault.

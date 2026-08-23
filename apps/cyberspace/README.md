# Cyberspace

Cyberspace is a human-operated SolarOS text client for the Cyberspace social
network. It provides feed and thread reading, posts and replies, notifications,
profiles and follows, search, topics, guilds, bookmarks, watched threads,
journal notes and revisions, settings, C-Mail, and cIRC.

The client is intentionally confined to this foreground application. It does
not provide a Native Agent tool, scripting API, background job, bot, scraper,
or automation interface. Cyberspace content must not be supplied to an AI
system. These boundaries follow the Cyberspace API terms for personal clients.

## Login and privacy

Enter credentials through the app's terminal UI. Password entry uses the native
SolarOS masked-input rendering option. The password is discarded after the
login request and is never saved.

The login screen places separate Email and Password boxes below a large
ASCII-art CYBERSPACE heading. Login, saved-login, and forget-saved controls are
selectable Unicode-box buttons. Use Up, Down, or Tab to move between the fields
and actions. Password input is always masked.

Remembered login is off by default. If you enable it, `session.json` is written
beside the installed entry script. That file contains only the account email
address and refresh token. The password and ID token are never stored. The
token is plaintext, and Playground applications are executable code rather than
sandboxes. A saved session is not used until you select **Use saved login**.
Select **Forget saved login** on the same screen, or log out, to delete the
file. Reinstalling or upgrading the app can also remove it.

Account creation remains on <https://cyberspace.online>. An unverified account
can request a new verification email from the login flow.

## Navigation

After login, the top bar provides the same flat screen model as cyber-tui:
Feed, Notifications, Email, IRC, Journal, Bookmarks, Guilds, Topics, Profile,
and Settings. The bar shows the active tab and automatically windows the labels
to fit narrow SolarOS terminals.

Feed entries, guilds and guild threads, C-Mail conversations, cIRC rooms, and
thread replies use selectable Unicode-bordered cards. Usernames, post titles,
conversation partners, and room names use bold text. Enter opens the selected
card. In a thread, Enter opens the complete selected post or reply in a
scrollable reader. Reply, bookmark, watch, and copy-link always target the
currently selected post or reply card.

Common controls:

- Arrow keys or `j`/`k`: move or scroll; Down loads the next page at the end
- Enter: open or select
- Ctrl-Left/Ctrl-Right: change tabs from any tab view
- Escape: go back
- `q`: exit the application from a list or reading view
- `r`: reply to the selected feed/thread card, or refresh where shown
- `n`: create an entry, note, thread, or conversation where available
- `/`: search from the feed
- Page Down: request the next bounded page and move forward one visible page

Action keys shown in the footer expose bookmark/watch/report/edit/delete,
profile, guild, notification, note-revision, attachment-copy, presence, and
message operations. Destructive and reporting operations require confirmation.
Attachment URLs can be copied to the shared SolarOS clipboard. Images, GIFs,
audio, and websites are represented as labeled URLs; no graphics or audio
service is required.

The multiline editor accepts UTF-8 input. Enter inserts a newline, Ctrl-S (or
Ctrl-D) submits, and Escape cancels. Entry, reply, and journal text is bounded
to 32,768 UTF-8 bytes. Smaller API limits are applied to titles, messages,
profile fields, search terms, and report reasons.

Open C-Mail conversations use left/right-aligned message boxes. cIRC rooms use
compact IRC-style `<username>  message  time` rows without per-message boxes.
Both have a persistent input box at the bottom. Enter sends the input. All
printable characters, including digits and `q`, go to that input; Left/Right
edits it, while Ctrl-Left/Ctrl-Right changes tabs directly. Page Up and Page
Down move by a full page;
Page Up automatically loads the next bounded history page when necessary.
Shift-Page Up and Shift-Page Down are accepted as keyboard-layout aliases.
Ctrl-O explicitly loads older history, Ctrl-R reconnects, and Ctrl-U opens the
cIRC user list. Chat renders `/art`, actions, deleted-message tombstones,
attachments, and style labels as terminal-safe text. Spoilers stay hidden until
explicitly revealed. C-Mail and cIRC use bounded REST history plus one live
Firebase SSE message stream for the open conversation or room. Streams stop
when the view closes, the user logs out, or the app exits.

Terminals smaller than 36 columns by 13 rows show a size warning. The interface
uses `solaros.tui`, so it works on the physical display terminal and on
cursor-addressable SSH, CDC, serial, or telnet shells.

## Requirements

Cyberspace requires SolarOS 4.8.9 or newer, Wi-Fi, the Python and Playground
packages, and the package-gated synchronous and streaming `solaros.http` APIs.
It does not require a graphics display or audio hardware. HTTPS uses the SolarOS
certificate bundle and always connects to `https://api.cyberspace.online` (and
the login-provided Firebase RTDB URL); custom endpoints and redirects are
disabled.

On firmware that provides retained `solaros.http` sessions, the REST client
keeps one same-origin HTTPS connection open for the foreground app and closes
it on exit. Older compatible firmware falls back to bounded one-shot requests.
Firebase SSE remains a separate streaming connection.

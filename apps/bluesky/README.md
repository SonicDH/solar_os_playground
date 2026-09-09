# BlueSky

BlueSky is a text-only AT Protocol client for SolarOS. It provides a compact,
keyboard-driven way to read and post on Bluesky, including accounts hosted on
personal data servers (PDSes).

## Features

- Sign in with a Bluesky app password and a manually selected PDS.
- Save login details locally for automatic sign-in.
- Read, refresh, and page through the home timeline.
- Switch between compact previews and fully wrapped post text in Home and
  profile timelines; the selected mode is remembered.
- Open complete posts and conversation threads.
- Browse an author's profile timeline or enter any handle.
- Compose text posts.
- Reply to posts from Home, profiles, threads, or the complete post view.
- Like/unlike directly from Home and profile timelines, or from the complete
  post view; repost/unrepost from the complete post view.
- Read accepted direct and group conversations, start one-to-one
  conversations, and send text replies.
- Stream larger API responses to disk to keep MicroPython memory use bounded.
- Update only the changed selector rows while moving through a timeline.

## First run and privacy

Enter the HTTPS origin of the account's PDS, such as
`https://pds.example.com`, the account handle, and a Bluesky app password. Use
an app password rather than the account's primary password.

The PDS address, handle, and app password are stored in `config.json` beside
the installed script. A normal SD-card Playground installation stores it at:

```text
/sdcard/playground/python/bluesky/config.json
```

This file is plain text. Treat the device and its storage as trusted. Access
and refresh tokens are kept only in interpreter memory and cleared when the
app exits. Expired access tokens are refreshed automatically during a running
session. To replace a saved login, run:

```text
playground run bluesky --login
```

## Controls

- Up/Down: move through lists or scroll a reader.
- Page Up/Page Down: move five posts in Home or one page in an open message
  conversation.
- Enter or Right: open the selected post.
- `r`: refresh the current timeline or message list.
- `v`: toggle compact or full-text display in Home and profile timelines.
- `n`: load the next timeline page.
- `c`: compose a post; Ctrl-D submits multiline text.
- `a`: reply to the selected post; Ctrl-D submits multiline text.
- `p`: open the selected author's timeline.
- `u`: enter a handle and open that user's timeline.
- `t`: open the selected post's thread.
- `d`: open messages; Enter opens a conversation and `c` writes a reply.
- In Messages, `n` starts a one-to-one conversation by handle.
- In Home, profiles, or a complete post, `l` toggles a like.
- In a complete post, `b` toggles a repost.
- Escape, Left, or `q`: go back or quit.

## Limitations

BlueSky does not perform automatic handle-to-PDS discovery or OAuth. It does
not currently support rich-text facets, images, notifications, message
requests, group-conversation creation, or attachments.

## Requirements

BlueSky requires SolarOS 4.8.4 or newer, Wi-Fi, and the Python and Playground
packages. It uses the package-gated synchronous and streaming `solaros.http`
APIs and the terminal UI, so it does not require a graphical display.

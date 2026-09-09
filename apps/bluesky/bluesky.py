"""BlueSky: a small text-only Bluesky client for SolarOS MicroPython."""

import json
import sys
import gc

import solaros
from solaros import tui


DEFAULT_SERVICE = "https://bsky.social"


def app_directory():
    path = sys.argv[0] if sys.argv else "bluesky.py"
    if not path or "/" not in path:
        try:
            path = __file__
        except NameError:
            path = "bluesky.py"
    separator = path.rfind("/")
    if separator < 0:
        return "."
    return path[:separator] if separator > 0 else "/"


APP_DIR = app_directory()
SETTINGS_PATH = APP_DIR + "/config.json"
TIMELINE_LIMIT = 12
CONVO_LIMIT = 20
MESSAGE_LIMIT = 40
HTTP_LIMIT = 65536
TIMELINE_DISK_LIMIT = 512 * 1024
TIMELINE_PATH = APP_DIR + "/timeline.json.tmp"
CHAT_PROXY = "did:web:api.bsky.chat#bsky_chat"

KEY_ENTER = 10
KEY_RETURN = 13
KEY_BACKSPACE = 8
KEY_DELETE_CHAR = 127


def clean_text(value):
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def clip(text, width):
    text = clean_text(text)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width < 2:
        return text[:width]
    return text[:width - 1] + "~"


def wrap(text, width):
    text = clean_text(text)
    if width < 1:
        return []
    if not text:
        return [""]
    lines = []
    remaining = text
    while remaining:
        if len(remaining) <= width:
            lines.append(remaining)
            break
        cut = remaining.rfind(" ", 0, width + 1)
        if cut < 1:
            cut = width
        lines.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    return lines


def show_message(title, message, help_text="Press any key"):
    rows, cols = tui.size()
    tui.clear()
    tui.addstr(0, 0, clip(" " + title + " ", cols), tui.INVERSE)
    line = 2
    for part in wrap(message, cols - 2):
        if line >= rows - 2:
            break
        tui.addstr(line, 1, part)
        line += 1
    tui.addstr(rows - 1, 0, clip(help_text, cols), tui.INVERSE)
    tui.refresh()


def wait_key():
    while not solaros.should_exit():
        key = tui.getch(250)
        if key is not None:
            return key
    return tui.KEY_ESCAPE


def confirm(title, message):
    show_message(title, message, "y confirm  any other key cancels")
    return wait_key() == ord("y")


def edit_text(title, label, initial="", masked=False, multiline=False,
              max_length=300):
    value = initial
    dirty = True
    while not solaros.should_exit():
        if dirty:
            rows, cols = tui.size()
            tui.clear()
            tui.addstr(0, 0, clip(" " + title + " ", cols), tui.INVERSE)
            tui.addstr(2, 1, clip(label, cols - 2), tui.BOLD)
            shown = "*" * len(value) if masked else value
            lines = wrap(shown, cols - 2)
            available = rows - 6
            if len(lines) > available:
                lines = lines[-available:]
            row = 4
            for part in lines:
                tui.addstr(row, 1, clip(part, cols - 2))
                row += 1
            if multiline:
                count = "{}/{}  Ctrl+D send  Esc cancel".format(
                    len(value), max_length)
            else:
                count = "Enter accept  Esc cancel"
            tui.addstr(rows - 1, 0, clip(count, cols), tui.INVERSE)
            tui.refresh()
            dirty = False

        key = tui.getch(250)
        if key is None:
            continue
        if key == tui.KEY_ESCAPE:
            return None
        if multiline and key == 4:  # Ctrl+D
            return value.strip()
        if not multiline and (key == KEY_ENTER or key == KEY_RETURN):
            return value.strip()
        if key == KEY_BACKSPACE or key == KEY_DELETE_CHAR or key == tui.KEY_DELETE:
            value = value[:-1]
            dirty = True
        elif multiline and (key == KEY_ENTER or key == KEY_RETURN):
            if len(value) < max_length:
                value += "\n"
                dirty = True
        elif isinstance(key, int) and 32 <= key <= 126:
            if len(value) < max_length:
                value += chr(key)
                dirty = True
    return None


def load_handle():
    return load_settings().get("handle", "")


def load_settings():
    try:
        with open(SETTINGS_PATH, "r") as source:
            data = json.loads(source.read())
        if not isinstance(data, dict):
            return {}
        result = {}
        handle = data.get("handle", "")
        service = data.get("service", DEFAULT_SERVICE)
        password = data.get("password", "")
        full_timeline = data.get("full_timeline", False)
        if isinstance(handle, str):
            result["handle"] = handle
        if isinstance(service, str):
            result["service"] = service
        if isinstance(password, str):
            result["password"] = password
        if isinstance(full_timeline, bool):
            result["full_timeline"] = full_timeline
        return result
    except Exception:
        return {}


def write_settings(settings):
    temp_path = SETTINGS_PATH + ".tmp"
    try:
        with open(temp_path, "w") as output:
            output.write(json.dumps(settings))
            output.flush()
        try:
            solaros.storage.remove(SETTINGS_PATH)
        except OSError:
            pass
        solaros.storage.rename(temp_path, SETTINGS_PATH)
    except Exception:
        try:
            solaros.storage.remove(temp_path)
        except Exception:
            pass


def save_settings(handle, service, password):
    full_timeline = load_settings().get("full_timeline", False)
    write_settings({
        "handle": handle,
        "service": service,
        "password": password,
        "full_timeline": full_timeline,
    })


def save_timeline_mode(enabled):
    settings = load_settings()
    settings["full_timeline"] = bool(enabled)
    write_settings(settings)


class AuthExpiredError(RuntimeError):
    pass


def decode_response(response):
    body = response.get("body", b"")
    if response.get("truncated"):
        raise RuntimeError("Server response was too large")
    try:
        data = json.loads(body)
    except Exception:
        raise RuntimeError("Server returned invalid JSON")
    status = response.get("status_code", 0)
    if status < 200 or status >= 300:
        message = data.get("message", "HTTP {}".format(status))
        if status == 401:
            raise AuthExpiredError(clean_text(message))
        raise RuntimeError(clean_text(message))
    return data


def stream_json(url, headers, path, max_bytes):
    handle = solaros.http.stream_open("GET", url, None, headers, 15000, False)
    status = 0
    received = 0
    try:
        with open(path, "wb") as output:
            while not solaros.should_exit():
                event = solaros.http.stream_read(handle, 1000)
                if event is None:
                    continue
                event_type = event.get("type")
                if event_type == "response":
                    status = event.get("status_code", 0)
                elif event_type == "data":
                    chunk = event.get("data", b"")
                    received += len(chunk)
                    if received > max_bytes:
                        raise RuntimeError("Timeline response exceeds disk limit")
                    output.write(chunk)
                elif event_type == "error":
                    raise RuntimeError(event.get("error_name", "HTTP stream error"))
                elif event_type == "complete":
                    break
            output.flush()
    finally:
        solaros.http.stream_close(handle)
        handle = None
        gc.collect()
    try:
        with open(path, "r") as source:
            data = json.load(source)
        if status < 200 or status >= 300:
            message = clean_text(data.get("message", "HTTP {}".format(status)))
            if status == 401:
                raise AuthExpiredError(message)
            raise RuntimeError(message)
        return data
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Server returned invalid JSON")
    finally:
        try:
            solaros.storage.remove(path)
        except OSError:
            pass
        gc.collect()


def compact_timeline_item(item):
    post = item.get("post", {})
    author = post.get("author", {})
    record = post.get("record", {})
    viewer = post.get("viewer", {})
    compact = {
        "post": {
            "uri": post.get("uri", ""),
            "cid": post.get("cid", ""),
            "author": {
                "displayName": author.get("displayName", ""),
                "handle": author.get("handle", ""),
            },
            "record": {"text": record.get("text", "")},
            "likeCount": post.get("likeCount", 0),
            "repostCount": post.get("repostCount", 0),
            "replyCount": post.get("replyCount", 0),
            "viewer": {
                "like": viewer.get("like", ""),
                "repost": viewer.get("repost", ""),
            },
        }
    }
    reason = item.get("reason")
    if reason:
        compact["reason"] = {"by": {"handle": reason.get("by", {}).get("handle", "")}}
    return compact


def flatten_thread(data):
    root = data.get("thread", {})
    result = []
    parents = []
    parent = root.get("parent") if isinstance(root, dict) else None
    while isinstance(parent, dict) and parent.get("post"):
        parents.append(parent)
        parent = parent.get("parent")
    for node in reversed(parents):
        item = compact_timeline_item(node)
        item["_depth"] = 0
        result.append(item)

    def add_node(node, depth):
        if not isinstance(node, dict) or not node.get("post") or len(result) >= 40:
            return
        item = compact_timeline_item(node)
        item["_depth"] = depth
        result.append(item)
        for reply in node.get("replies", []):
            add_node(reply, min(4, depth + 1))

    add_node(root, 0)
    return result


class Client:
    def __init__(self, service):
        self.service = service
        self.access_jwt = ""
        self.refresh_jwt = ""
        self.did = ""
        self.handle = ""
        self.cursor = None
        self.author_cursor = None

    def headers(self):
        return {
            "Authorization": "Bearer " + self.access_jwt,
            "Accept": "application/json",
        }

    def chat_headers(self):
        headers = self.headers()
        headers["atproto-proxy"] = CHAT_PROXY
        return headers

    def refresh_session(self):
        if not self.refresh_jwt:
            raise AuthExpiredError("Session expired; sign in again")
        headers = {
            "Authorization": "Bearer " + self.refresh_jwt,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        response = solaros.http.post(
            self.service + "/xrpc/com.atproto.server.refreshSession",
            "{}", headers, 15000, HTTP_LIMIT, False)
        data = decode_response(response)
        self.access_jwt = data["accessJwt"]
        self.refresh_jwt = data["refreshJwt"]
        self.did = data.get("did", self.did)
        self.handle = data.get("handle", self.handle)

    def stream_get(self, url, path, max_bytes):
        try:
            return stream_json(url, self.headers(), path, max_bytes)
        except AuthExpiredError:
            self.refresh_session()
            return stream_json(url, self.headers(), path, max_bytes)

    def post_json(self, method, payload, authenticated=True):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.access_jwt
        response = solaros.http.post(
            self.service + "/xrpc/" + method,
            json.dumps(payload),
            headers,
            15000,
            HTTP_LIMIT,
            False,
        )
        if authenticated and response.get("status_code") == 401:
            self.refresh_session()
            headers["Authorization"] = "Bearer " + self.access_jwt
            response = solaros.http.post(
                self.service + "/xrpc/" + method, json.dumps(payload), headers,
                15000, HTTP_LIMIT, False)
        return decode_response(response)

    def get_json(self, method, query="", authenticated=True):
        url = self.service + "/xrpc/" + method
        if query:
            url += "?" + query
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.access_jwt
        response = solaros.http.get(url, headers, 15000, HTTP_LIMIT, False)
        if authenticated and response.get("status_code") == 401:
            self.refresh_session()
            headers["Authorization"] = "Bearer " + self.access_jwt
            response = solaros.http.get(url, headers, 15000, HTTP_LIMIT, False)
        return decode_response(response)

    def chat_get(self, method, query=""):
        url = self.service + "/xrpc/" + method
        if query:
            url += "?" + query
        response = solaros.http.get(
            url, self.chat_headers(), 15000, HTTP_LIMIT, False)
        if response.get("status_code") == 401:
            self.refresh_session()
            response = solaros.http.get(
                url, self.chat_headers(), 15000, HTTP_LIMIT, False)
        return decode_response(response)

    def chat_post(self, method, payload):
        headers = self.chat_headers()
        headers["Content-Type"] = "application/json"
        response = solaros.http.post(
            self.service + "/xrpc/" + method,
            json.dumps(payload), headers, 15000, HTTP_LIMIT, False)
        if response.get("status_code") == 401:
            self.refresh_session()
            headers = self.chat_headers()
            headers["Content-Type"] = "application/json"
            response = solaros.http.post(
                self.service + "/xrpc/" + method,
                json.dumps(payload), headers, 15000, HTTP_LIMIT, False)
        return decode_response(response)

    def login(self, identifier, password):
        data = self.post_json(
            "com.atproto.server.createSession",
            {"identifier": identifier, "password": password},
            False,
        )
        self.access_jwt = data["accessJwt"]
        self.refresh_jwt = data["refreshJwt"]
        self.did = data["did"]
        self.handle = data["handle"]

    def timeline(self, cursor=None):
        url = self.service + "/xrpc/app.bsky.feed.getTimeline?limit={}".format(
            TIMELINE_LIMIT)
        if cursor:
            url += "&cursor=" + quote(cursor)
        data = self.stream_get(url, TIMELINE_PATH, TIMELINE_DISK_LIMIT)
        self.cursor = data.get("cursor")
        compact = []
        for item in data.get("feed", []):
            compact.append(compact_timeline_item(item))
        data = None
        gc.collect()
        return compact

    def author_feed(self, actor, cursor=None):
        url = self.service + "/xrpc/app.bsky.feed.getAuthorFeed?actor={}&limit={}".format(
            quote(actor), TIMELINE_LIMIT)
        if cursor:
            url += "&cursor=" + quote(cursor)
        data = self.stream_get(url, TIMELINE_PATH, TIMELINE_DISK_LIMIT)
        self.author_cursor = data.get("cursor")
        result = [compact_timeline_item(item) for item in data.get("feed", [])]
        data = None
        gc.collect()
        return result

    def post_thread(self, uri):
        url = self.service + "/xrpc/app.bsky.feed.getPostThread?uri={}&depth=6&parentHeight=6".format(
            quote(uri))
        data = self.stream_get(url, TIMELINE_PATH, TIMELINE_DISK_LIMIT)
        result = flatten_thread(data)
        data = None
        gc.collect()
        return result

    def create_post(self, text):
        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": utc_timestamp(),
        }
        return self.post_json(
            "com.atproto.repo.createRecord",
            {
                "repo": self.did,
                "collection": "app.bsky.feed.post",
                "record": record,
            },
        )

    def create_record(self, collection, record):
        return self.post_json(
            "com.atproto.repo.createRecord",
            {"repo": self.did, "collection": collection, "record": record},
        )

    def delete_record(self, collection, uri):
        prefix = "at://" + self.did + "/" + collection + "/"
        if not uri.startswith(prefix):
            raise RuntimeError("Server returned an invalid interaction record")
        rkey = uri[len(prefix):]
        if not rkey or "/" in rkey:
            raise RuntimeError("Server returned an invalid interaction key")
        return self.post_json(
            "com.atproto.repo.deleteRecord",
            {"repo": self.did, "collection": collection, "rkey": rkey},
        )

    def toggle_reaction(self, item, kind):
        post = item.get("post", {})
        uri = post.get("uri", "")
        cid = post.get("cid", "")
        if not uri or not cid:
            raise RuntimeError("This post has no complete AT Protocol reference")
        collection = "app.bsky.feed." + kind
        viewer = post.setdefault("viewer", {})
        existing = viewer.get(kind, "")
        count_key = kind + "Count"
        if existing:
            self.delete_record(collection, existing)
            viewer[kind] = ""
            post[count_key] = max(0, post.get(count_key, 0) - 1)
            return False
        result = self.create_record(collection, {
            "$type": collection,
            "subject": {"uri": uri, "cid": cid},
            "createdAt": utc_timestamp(),
        })
        record_uri = result.get("uri", "")
        if not record_uri:
            raise RuntimeError("Server did not return the interaction record")
        viewer[kind] = record_uri
        post[count_key] = post.get(count_key, 0) + 1
        return True

    def resolve_actor(self, actor):
        actor = actor.strip()
        while actor.startswith("@"):
            actor = actor[1:]
        if actor.startswith("did:"):
            return actor
        if not actor:
            raise RuntimeError("Enter a Bluesky handle")
        data = self.get_json(
            "com.atproto.identity.resolveHandle", "handle=" + quote(actor), False)
        did = data.get("did", "")
        if not did.startswith("did:"):
            raise RuntimeError("Could not resolve that handle")
        return did

    def list_convos(self):
        data = self.chat_get(
            "chat.bsky.convo.listConvos",
            "limit={}&status=accepted".format(CONVO_LIMIT))
        return data.get("convos", [])

    def convo_for_actor(self, actor):
        did = self.resolve_actor(actor)
        data = self.chat_get(
            "chat.bsky.convo.getConvoForMembers", "members=" + quote(did))
        convo = data.get("convo")
        if not isinstance(convo, dict) or not convo.get("id"):
            raise RuntimeError("Chat service did not return a conversation")
        return convo

    def get_messages(self, convo_id):
        data = self.chat_get(
            "chat.bsky.convo.getMessages",
            "convoId={}&limit={}".format(quote(convo_id), MESSAGE_LIMIT))
        return data.get("messages", [])

    def send_message(self, convo_id, text):
        return self.chat_post(
            "chat.bsky.convo.sendMessage",
            {"convoId": convo_id, "message": {"text": text}})


def quote(value):
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    result = ""
    for byte in value.encode("utf-8"):
        ch = chr(byte)
        if ch in safe:
            result += ch
        else:
            result += "%{:02X}".format(byte)
    return result


def utc_timestamp():
    value = solaros.time.utc_datetime()
    if not value.get("clock_integrity", True):
        try:
            solaros.time.ntp_sync()
            value = solaros.time.utc_datetime()
        except OSError:
            pass
    return ("{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.000Z".format(
        value["year"], value["month"], value["day"], value["hour"],
        value["minute"], value["second"]))


def post_summary(item):
    post = item.get("post", {})
    author = post.get("author", {})
    record = post.get("record", {})
    name = clean_text(author.get("displayName") or author.get("handle") or "Unknown")
    handle = clean_text(author.get("handle", ""))
    text = clean_text(record.get("text", ""))
    reason = item.get("reason")
    if reason:
        by = reason.get("by", {}).get("handle", "")
        if by:
            name = "repost by @" + clean_text(by) + " | " + name
    depth = item.get("_depth", 0)
    if depth:
        name = ("  " * depth) + "- " + name
    return name, handle, text


def timeline_item_height(item, cols, full_text):
    if not full_text:
        return 3
    unused_name, unused_handle, text = post_summary(item)
    return max(3, len(wrap(text, max(1, cols - 5))) + 2)


def timeline_layout(feed, selected, rows, cols, full_text):
    if not feed:
        return []
    body_rows = max(1, rows - 2)
    heights = [min(body_rows, timeline_item_height(item, cols, full_text))
               for item in feed]
    start = min(max(0, selected), len(feed) - 1)
    used = heights[start]
    while start > 0 and used + heights[start - 1] <= body_rows:
        start -= 1
        used += heights[start]
    result = []
    row = 1
    index = start
    while index < len(feed) and row - 1 + heights[index] <= body_rows:
        result.append((index, row, heights[index]))
        row += heights[index]
        index += 1
    return result


def draw_timeline(feed, selected, message="", title="BlueSky", footer=None,
                  full_text=False):
    rows, cols = tui.size()
    tui.clear()
    heading = " " + title + " "
    if message:
        heading += "| " + message + " "
    tui.addstr(0, 0, clip(heading, cols), tui.INVERSE)
    for index, row, height in timeline_layout(feed, selected, rows, cols, full_text):
        draw_timeline_item(feed[index], row, index == selected, cols, full_text, height)
    if footer is None:
        footer = "Enter open  p profile  t thread  u user  r refresh  n next"
    tui.addstr(rows - 1, 0,
               clip(footer, cols),
               tui.INVERSE)
    tui.refresh()


def draw_timeline_item(item, row, selected, cols, full_text=False, height=3):
    name, handle, text = post_summary(item)
    attr = tui.INVERSE if selected else tui.BOLD
    prefix = "> " if selected else "  "
    byline = prefix + name
    if handle:
        byline += "  @" + handle
    for clear_row in range(row, row + height):
        tui.addstr(clear_row, 0, " " * cols)
    tui.addstr(row, 0, clip(byline, cols), attr)
    parts = wrap(text, cols - 5)
    limit = max(0, height - (2 if full_text else 1))
    for index, part in enumerate(parts[:limit]):
        tui.addstr(row + 1 + index, 4, clip(part, cols - 5))


def move_timeline_selector(feed, old, new, full_text=False):
    if old == new:
        return True
    rows, cols = tui.size()
    old_layout = timeline_layout(feed, old, rows, cols, full_text)
    new_layout = timeline_layout(feed, new, rows, cols, full_text)
    if old_layout != new_layout:
        return False
    positions = {index: (row, height) for index, row, height in old_layout}
    old_row, old_height = positions[old]
    new_row, new_height = positions[new]
    draw_timeline_item(feed[old], old_row, False, cols, full_text, old_height)
    draw_timeline_item(feed[new], new_row, True, cols, full_text, new_height)
    tui.refresh()
    return True


def show_thread(client, item, options=None):
    uri = item.get("post", {}).get("uri", "")
    if not uri:
        show_message("Thread", "This post has no thread identifier.")
        wait_key()
        return
    show_message("Thread", "Loading conversation...", "Please wait")
    posts = client.post_thread(uri)
    selected = 0
    dirty = True
    while not solaros.should_exit():
        if dirty:
            draw_timeline(posts, selected, "{} posts".format(len(posts)),
                          "Thread", "Up/Down Enter open  p profile  Esc back")
            dirty = False
        key = tui.getch(250)
        if key is None:
            continue
        if key == tui.KEY_ESCAPE or key == tui.KEY_LEFT or key == ord("q"):
            return
        if key == tui.KEY_DOWN and selected + 1 < len(posts):
            new_selected = selected + 1
            dirty = not move_timeline_selector(posts, selected, new_selected)
            selected = new_selected
        elif key == tui.KEY_UP and selected > 0:
            new_selected = selected - 1
            dirty = not move_timeline_selector(posts, selected, new_selected)
            selected = new_selected
        elif (key == KEY_ENTER or key == KEY_RETURN or key == tui.KEY_RIGHT) and posts:
            show_post(client, posts[selected])
            dirty = True
        elif key == ord("p") and posts:
            handle = posts[selected].get("post", {}).get("author", {}).get("handle", "")
            if handle:
                show_author_feed(client, handle, options)
            dirty = True


def show_author_feed(client, actor, options=None):
    if options is None:
        options = {"full_text": False}
    show_message("Profile", "Loading @" + actor + "...", "Please wait")
    posts = client.author_feed(actor)
    selected = 0
    note = "{} posts".format(len(posts))
    dirty = True
    while not solaros.should_exit():
        if dirty:
            draw_timeline(posts, selected, note, "@" + actor,
                          "Enter open  l like  v view  t thread  r refresh",
                          options["full_text"])
            note = ""
            dirty = False
        key = tui.getch(250)
        if key is None:
            continue
        if key == tui.KEY_ESCAPE or key == tui.KEY_LEFT or key == ord("q"):
            return
        if key == tui.KEY_DOWN and selected + 1 < len(posts):
            new_selected = selected + 1
            dirty = not move_timeline_selector(
                posts, selected, new_selected, options["full_text"])
            selected = new_selected
        elif key == tui.KEY_UP and selected > 0:
            new_selected = selected - 1
            dirty = not move_timeline_selector(
                posts, selected, new_selected, options["full_text"])
            selected = new_selected
        elif (key == KEY_ENTER or key == KEY_RETURN or key == tui.KEY_RIGHT) and posts:
            show_post(client, posts[selected])
            dirty = True
        elif key == ord("t") and posts:
            show_thread(client, posts[selected], options)
            dirty = True
        elif key == ord("l") and posts:
            note = toggle_reaction_ui(client, posts[selected], "like")
            dirty = True
        elif key == ord("v"):
            options["full_text"] = not options["full_text"]
            save_timeline_mode(options["full_text"])
            note = "full text" if options["full_text"] else "compact view"
            dirty = True
        elif key == ord("r"):
            posts = client.author_feed(actor)
            selected = 0
            note = "refreshed"
            dirty = True
        elif key == ord("n") and client.author_cursor:
            more = client.author_feed(actor, client.author_cursor)
            posts.extend(more)
            note = "{} posts".format(len(posts))
            dirty = True


def toggle_reaction_ui(client, item, kind):
    label = "like" if kind == "like" else "repost"
    show_message("BlueSky", "Updating " + label + "...", "Please wait")
    try:
        active = client.toggle_reaction(item, kind)
        return ("liked" if kind == "like" else "reposted") if active else (
            "like removed" if kind == "like" else "repost removed")
    except Exception as error:
        show_message("BlueSky error", str(error), "Press any key")
        wait_key()
        return ""


def show_post(client, item):
    name, handle, text = post_summary(item)
    post = item.get("post", {})
    rows, cols = tui.size()
    lines = wrap(text, cols - 2)
    offset = 0
    note = ""
    dirty = True
    while not solaros.should_exit():
        if dirty:
            tui.clear()
            heading = " " + name + " "
            if note:
                heading += "| " + note + " "
            tui.addstr(0, 0, clip(heading, cols), tui.INVERSE)
            note = ""
            tui.addstr(1, 1, clip("@" + handle, cols - 2), tui.BOLD)
            row = 3
            for line in lines[offset:]:
                if row >= rows - 3:
                    break
                tui.addstr(row, 1, line)
                row += 1
            counts = post.get("likeCount", 0), post.get("repostCount", 0), post.get("replyCount", 0)
            viewer = post.get("viewer", {})
            markers = ("*" if viewer.get("like") else "", "*" if viewer.get("repost") else "")
            tui.addstr(rows - 2, 1,
                       clip("{}{} likes  {}{} reposts  {} replies".format(
                           markers[0], counts[0], markers[1], counts[1], counts[2]), cols - 2))
            tui.addstr(rows - 1, 0,
                       clip("Up/Down scroll  l like  b repost  Esc back", cols),
                       tui.INVERSE)
            tui.refresh()
            dirty = False
        key = tui.getch(250)
        if key == tui.KEY_ESCAPE or key == tui.KEY_LEFT or key == ord("q"):
            return
        if key == tui.KEY_DOWN and offset < max(0, len(lines) - (rows - 6)):
            offset += 1
            dirty = True
        elif key == tui.KEY_UP and offset > 0:
            offset -= 1
            dirty = True
        elif key == ord("l"):
            note = toggle_reaction_ui(client, item, "like")
            dirty = True
        elif key == ord("b"):
            note = toggle_reaction_ui(client, item, "repost")
            dirty = True


def convo_name(convo, own_did):
    kind = convo.get("kind", {})
    if kind.get("$type", "").endswith("#groupConvo"):
        return clean_text(kind.get("name") or "Group conversation")
    names = []
    for member in convo.get("members", []):
        if member.get("did") == own_did:
            continue
        names.append(clean_text(
            member.get("displayName") or member.get("handle") or "Unknown"))
    return ", ".join(names) or "Conversation"


def draw_convos(convos, selected, own_did, note=""):
    rows, cols = tui.size()
    tui.clear()
    title = " Messages "
    if note:
        title += "| " + note + " "
    tui.addstr(0, 0, clip(title, cols), tui.INVERSE)
    visible = max(1, (rows - 2) // 3)
    start = (selected // visible) * visible
    row = 1
    for index in range(start, min(len(convos), start + visible)):
        convo = convos[index]
        unread = convo.get("unreadCount", 0)
        prefix = "> " if index == selected else "  "
        name = prefix + convo_name(convo, own_did)
        if unread:
            name += "  [{} new]".format(unread)
        attr = tui.INVERSE if index == selected else tui.BOLD
        tui.addstr(row, 0, clip(name, cols), attr)
        last = convo.get("lastMessage", {})
        sender = last.get("sender", {}).get("did")
        who = "You: " if sender == own_did else ""
        parts = wrap(who + clean_text(last.get("text", "")), cols - 5)
        tui.addstr(row + 1, 4, clip(parts[0] if parts else "", cols - 5))
        tui.addstr(row + 2, 4, clip(parts[1] if len(parts) > 1 else "", cols - 5))
        row += 3
    if not convos:
        tui.addstr(3, 2, "No accepted conversations")
    tui.addstr(rows - 1, 0,
               clip("Up/Down Enter open  n new  r refresh  Esc feed", cols), tui.INVERSE)
    tui.refresh()


def message_lines(messages, own_did, width):
    result = []
    # The service returns newest first; the reading view is chronological.
    for message in reversed(messages):
        if "text" not in message:
            result.append(("  [message unavailable]", tui.BOLD))
            continue
        mine = message.get("sender", {}).get("did") == own_did
        result.append((("You" if mine else "Them") + ":", tui.BOLD))
        for part in wrap(message.get("text", ""), max(1, width - 5)):
            result.append(("    " + part, 0))
        result.append(("", 0))
    return result


def show_conversation(client, convo):
    name = convo_name(convo, client.did)
    show_message("Messages", "Loading conversation...", "Please wait")
    messages = client.get_messages(convo.get("id", ""))
    offset = 1000000
    note = ""
    dirty = True
    while not solaros.should_exit():
        if dirty:
            rows, cols = tui.size()
            lines = message_lines(messages, client.did, cols)
            page = max(1, rows - 2)
            maximum = max(0, len(lines) - page)
            if offset > maximum:
                offset = maximum
            tui.clear()
            heading = " " + name + " "
            if note:
                heading += "| " + note + " "
            tui.addstr(0, 0, clip(heading, cols), tui.INVERSE)
            row = 1
            for text, attr in lines[offset:offset + page]:
                tui.addstr(row, 0, clip(text, cols), attr)
                row += 1
            tui.addstr(rows - 1, 0,
                       clip("Up/Down scroll  c reply  r refresh  Esc back", cols),
                       tui.INVERSE)
            tui.refresh()
            dirty = False
        key = tui.getch(250)
        if key is None:
            continue
        if key == tui.KEY_ESCAPE or key == tui.KEY_LEFT or key == ord("q"):
            return
        if key == tui.KEY_DOWN:
            offset = min(maximum, offset + 1)
            dirty = True
        elif key == tui.KEY_UP:
            offset = max(0, offset - 1)
            dirty = True
        elif key == tui.KEY_PAGE_DOWN:
            offset = min(maximum, offset + page)
            dirty = True
        elif key == tui.KEY_PAGE_UP:
            offset = max(0, offset - page)
            dirty = True
        elif key == ord("r"):
            show_message("Messages", "Refreshing...", "Please wait")
            messages = client.get_messages(convo.get("id", ""))
            offset = 1000000
            note = "refreshed"
            dirty = True
        elif key == ord("c"):
            text = edit_text("Reply", "Message " + name, "", False, True, 1000)
            if text and confirm("Send message?", clip(text, 180)):
                show_message("Messages", "Sending...", "Please wait")
                client.send_message(convo.get("id", ""), text)
                messages = client.get_messages(convo.get("id", ""))
                offset = 1000000
                note = "sent"
                dirty = True
            else:
                dirty = True


def start_conversation(client):
    actor = edit_text("New conversation", "Bluesky handle", "", False, False, 192)
    if not actor:
        return None
    text = edit_text("New conversation", "First message", "", False, True, 1000)
    if not text or not confirm("Send message?", clip(text, 180)):
        return None
    show_message("Messages", "Starting conversation...", "Please wait")
    convo = client.convo_for_actor(actor)
    client.send_message(convo.get("id", ""), text)
    return convo


def show_conversations(client):
    show_message("Messages", "Loading conversations...", "Please wait")
    convos = client.list_convos()
    selected = 0
    note = ""
    dirty = True
    while not solaros.should_exit():
        if dirty:
            draw_convos(convos, selected, client.did, note)
            note = ""
            dirty = False
        key = tui.getch(250)
        if key is None:
            continue
        if key == tui.KEY_ESCAPE or key == tui.KEY_LEFT or key == ord("q"):
            return
        if key == tui.KEY_DOWN and selected + 1 < len(convos):
            selected += 1
            dirty = True
        elif key == tui.KEY_UP and selected > 0:
            selected -= 1
            dirty = True
        elif (key == KEY_ENTER or key == KEY_RETURN or key == tui.KEY_RIGHT) and convos:
            show_conversation(client, convos[selected])
            dirty = True
        elif key == ord("n"):
            try:
                convo = start_conversation(client)
                if convo:
                    show_conversation(client, convo)
                    convos = client.list_convos()
                    selected = 0
                    note = "conversation started"
            except Exception as error:
                show_message("Messages error", str(error), "Press any key")
                wait_key()
            dirty = True
        elif key == ord("r"):
            show_message("Messages", "Refreshing...", "Please wait")
            convos = client.list_convos()
            selected = min(selected, max(0, len(convos) - 1))
            note = "refreshed"
            dirty = True


def normalize_service(value):
    value = value.strip()
    while value.endswith("/"):
        value = value[:-1]
    if not value.startswith("https://"):
        raise ValueError("PDS must start with https://")
    authority = value[8:]
    if not authority or "/" in authority or "@" in authority or "?" in authority or "#" in authority:
        raise ValueError("Enter only the PDS origin, without a path")
    return value


def draw_login(fields, selected, error=""):
    rows, cols = tui.size()
    tui.clear()
    tui.addstr(0, 0, clip(" BlueSky sign in ", cols), tui.INVERSE)
    labels = ("PDS server", "Handle or email", "App password")
    field_rows = (3, 8, 13)
    for index in range(3):
        attr = tui.INVERSE if index == selected else tui.BOLD
        tui.addstr(field_rows[index], 1, clip(" " + labels[index] + " ", cols - 2), attr)
        value = "*" * len(fields[index]) if index == 2 else fields[index]
        available = cols - 4
        tui.addstr(field_rows[index] + 2, 3, clip(value[-available:], available))
    if error:
        tui.addstr(rows - 3, 1, clip(error, cols - 2), tui.BOLD)
    tui.addstr(rows - 1, 0,
               clip("Up/Down choose  Enter next/sign in  Esc cancel", cols),
               tui.INVERSE)
    tui.refresh()


def login(force_prompt=False):
    settings = load_settings()
    fields = [settings.get("service", DEFAULT_SERVICE),
              settings.get("handle", ""), settings.get("password", "")]
    if not force_prompt and fields[0] and fields[1] and fields[2]:
        try:
            service = normalize_service(fields[0])
            client = Client(service)
            show_message("BlueSky", "Signing in with saved login...", "Please wait")
            client.login(fields[1], fields[2])
            return client
        except Exception:
            # Fall through to the editable form when saved credentials expire.
            pass
    limits = (192, 192, 128)
    selected = 0
    dirty = True
    error = ""
    while not solaros.should_exit():
        if dirty:
            draw_login(fields, selected, error)
            dirty = False
        key = tui.getch(250)
        if key is None:
            continue
        error = ""
        if key == tui.KEY_ESCAPE:
            return None
        if key == tui.KEY_UP:
            selected = (selected - 1) % 3
            dirty = True
        elif key == tui.KEY_DOWN or key == 9:
            selected = (selected + 1) % 3
            dirty = True
        elif key == KEY_ENTER or key == KEY_RETURN:
            if selected < 2:
                selected += 1
                dirty = True
            else:
                try:
                    service = normalize_service(fields[0])
                except ValueError as caught:
                    selected = 0
                    error = str(caught)
                    dirty = True
                    continue
                handle = fields[1].strip()
                password = fields[2]
                if not handle:
                    selected = 1
                    error = "Handle is required"
                    dirty = True
                    continue
                if not password:
                    error = "App password is required"
                    dirty = True
                    continue
                break
        elif key == KEY_BACKSPACE or key == KEY_DELETE_CHAR or key == tui.KEY_DELETE:
            fields[selected] = fields[selected][:-1]
            dirty = True
        elif isinstance(key, int) and 32 <= key <= 126:
            if len(fields[selected]) < limits[selected]:
                fields[selected] += chr(key)
                dirty = True
    else:
        return None
    client = Client(service)
    show_message("BlueSky", "Signing in...", "Esc cancels application")
    client.login(handle, password)
    password = ""
    save_settings(client.handle, service, fields[2])
    return client


def main():
    client = None
    try:
        client = login("--login" in sys.argv)
        if client is None:
            return
        show_message("BlueSky", "Loading home timeline...", "Please wait")
        feed = client.timeline()
        options = {"full_text": load_settings().get("full_timeline", False)}
        selected = 0
        note = "@" + client.handle
        dirty = True
        while not solaros.should_exit():
            if dirty:
                draw_timeline(
                    feed, selected, note, "BlueSky",
                    "Enter open  l like  v view  p profile  r refresh",
                    options["full_text"])
                note = ""
                dirty = False
            key = tui.getch(250)
            if key is None:
                continue
            if key == tui.KEY_ESCAPE or key == ord("q"):
                break
            if key == tui.KEY_DOWN and selected + 1 < len(feed):
                new_selected = selected + 1
                dirty = not move_timeline_selector(
                    feed, selected, new_selected, options["full_text"])
                selected = new_selected
            elif key == tui.KEY_UP and selected > 0:
                new_selected = selected - 1
                dirty = not move_timeline_selector(
                    feed, selected, new_selected, options["full_text"])
                selected = new_selected
            elif key == tui.KEY_PAGE_DOWN and feed:
                new_selected = min(len(feed) - 1, selected + 5)
                dirty = not move_timeline_selector(
                    feed, selected, new_selected, options["full_text"])
                selected = new_selected
            elif key == tui.KEY_PAGE_UP and feed:
                new_selected = max(0, selected - 5)
                dirty = not move_timeline_selector(
                    feed, selected, new_selected, options["full_text"])
                selected = new_selected
            elif (key == KEY_ENTER or key == KEY_RETURN or key == tui.KEY_RIGHT) and feed:
                show_post(client, feed[selected])
                dirty = True
            elif key == ord("r"):
                show_message("BlueSky", "Refreshing...", "Please wait")
                feed = client.timeline()
                selected = 0
                note = "refreshed"
                dirty = True
            elif key == ord("n") and client.cursor:
                show_message("BlueSky", "Loading more posts...", "Please wait")
                more = client.timeline(client.cursor)
                if more:
                    feed.extend(more)
                    note = "{} posts".format(len(feed))
                else:
                    note = "no more posts"
                dirty = True
            elif key == ord("p") and feed:
                handle = feed[selected].get("post", {}).get("author", {}).get("handle", "")
                if handle:
                    show_author_feed(client, handle, options)
                dirty = True
            elif key == ord("u"):
                handle = edit_text("View profile", "Handle", "", False, False, 192)
                if handle:
                    while handle.startswith("@"):
                        handle = handle[1:]
                    show_author_feed(client, handle, options)
                dirty = True
            elif key == ord("t") and feed:
                show_thread(client, feed[selected], options)
                dirty = True
            elif key == ord("l") and feed:
                note = toggle_reaction_ui(client, feed[selected], "like")
                dirty = True
            elif key == ord("v"):
                options["full_text"] = not options["full_text"]
                save_timeline_mode(options["full_text"])
                note = "full text" if options["full_text"] else "compact view"
                dirty = True
            elif key == ord("c"):
                text = edit_text("New post", "Write a post", "", False, True, 300)
                if text:
                    show_message("BlueSky", "Publishing...", "Please wait")
                    client.create_post(text)
                    feed = client.timeline()
                    selected = 0
                    note = "posted"
                    dirty = True
            elif key == ord("d"):
                show_conversations(client)
                note = "@" + client.handle
                dirty = True
    except KeyboardInterrupt:
        pass
    except Exception as error:
        show_message("BlueSky error", str(error), "Press any key")
        wait_key()
    finally:
        if client is not None:
            client.access_jwt = ""
            client.refresh_jwt = ""
        tui.clear()
        tui.refresh()


if __name__ == "__main__":
    main()

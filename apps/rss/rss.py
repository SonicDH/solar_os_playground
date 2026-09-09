"""Offline-first text RSS/Atom reader for SolarOS MicroPython."""

import json
import gc
import sys

import solaros
from solaros import tui


def app_directory():
    path = sys.argv[0] if sys.argv else "rss.py"
    if not path or "/" not in path:
        try:
            path = __file__
        except NameError:
            path = "rss.py"
    separator = path.rfind("/")
    if separator < 0:
        return "."
    return path[:separator] if separator > 0 else "/"


APP_DIR = app_directory()
FEEDS_PATH = APP_DIR + "/feeds.json"
CACHE_PATH = APP_DIR + "/cache.json"
BODY_DIR = APP_DIR + "/articles"
FEED_TEMP = APP_DIR + "/feed.xml.tmp"
STARTER_FEEDS_VERSION = 1
STARTER_FEEDS = [
    {"title": "BBC World News",
     "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"title": "Hackaday",
     "url": "https://hackaday.com/blog/feed/"},
    {"title": "Hacker News",
     "url": "https://hnrss.org/frontpage"},
]
DEFAULT_LIMIT = 10
HTTP_LIMIT = 256 * 1024
ARTICLE_LIMIT = 12 * 1024
ENTRY_BUFFER_LIMIT = 48 * 1024

KEY_ENTER = 10
KEY_RETURN = 13
KEY_BACKSPACE = 8
KEY_DELETE_CHAR = 127


def clean_space(value):
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def clip(value, width):
    value = clean_space(value)
    if len(value) <= width:
        return value
    return value[:max(0, width - 1)] + ("~" if width else "")


def wrap(value, width):
    if width < 1:
        return []
    result = []
    for paragraph in str(value or "").replace("\r", "").split("\n"):
        paragraph = clean_space(paragraph)
        if not paragraph:
            if result and result[-1] != "":
                result.append("")
            continue
        while len(paragraph) > width:
            cut = paragraph.rfind(" ", 0, width + 1)
            if cut < 1:
                cut = width
            result.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        result.append(paragraph)
    return result or [""]


def show_message(title, body, footer="Press any key"):
    rows, cols = tui.size()
    tui.clear()
    tui.addstr(0, 0, clip(" " + title + " ", cols), tui.INVERSE)
    row = 2
    for line in wrap(body, cols - 2):
        if row >= rows - 1:
            break
        tui.addstr(row, 1, line)
        row += 1
    tui.addstr(rows - 1, 0, clip(footer, cols), tui.INVERSE)
    tui.refresh()


def wait_key():
    while not solaros.should_exit():
        key = tui.getch(250)
        if key is not None:
            return key
    return tui.KEY_ESCAPE


def edit_text(title, label, initial="", max_length=512):
    value = initial
    dirty = True
    while not solaros.should_exit():
        if dirty:
            rows, cols = tui.size()
            tui.clear()
            tui.addstr(0, 0, clip(" " + title + " ", cols), tui.INVERSE)
            tui.addstr(2, 1, clip(label, cols - 2), tui.BOLD)
            parts = wrap(value, cols - 2)
            row = 4
            for part in parts[-max(1, rows - 6):]:
                tui.addstr(row, 1, part)
                row += 1
            tui.addstr(rows - 1, 0,
                       clip("Enter accept  Esc cancel", cols), tui.INVERSE)
            tui.refresh()
            dirty = False
        key = tui.getch(250)
        if key is None:
            continue
        if key == tui.KEY_ESCAPE:
            return None
        if key == KEY_ENTER or key == KEY_RETURN:
            return value.strip()
        if key == KEY_BACKSPACE or key == KEY_DELETE_CHAR or key == tui.KEY_DELETE:
            value = value[:-1]
            dirty = True
        elif isinstance(key, int) and 32 <= key <= 126 and len(value) < max_length:
            value += chr(key)
            dirty = True
    return None


def atomic_json(path, data):
    temporary = path + ".tmp"
    with open(temporary, "w") as output:
        json.dump(data, output)
        output.flush()
    try:
        solaros.storage.remove(path)
    except OSError:
        pass
    solaros.storage.rename(temporary, path)


def load_json(path, fallback):
    try:
        with open(path, "r") as source:
            value = json.load(source)
        return value
    except Exception:
        return fallback


def load_config():
    data = load_json(FEEDS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    feeds = data.get("feeds", [])
    if not isinstance(feeds, list):
        feeds = []
    clean = []
    for feed in feeds:
        if isinstance(feed, dict) and isinstance(feed.get("url"), str):
            clean.append({"url": feed["url"],
                          "title": clean_space(feed.get("title", ""))})
        elif isinstance(feed, str):
            clean.append({"url": feed, "title": ""})
    starter_version = data.get("starter_feeds_version", 0)
    if not isinstance(starter_version, int):
        starter_version = 0
    if starter_version < STARTER_FEEDS_VERSION:
        known = [feed["url"] for feed in clean]
        for starter in STARTER_FEEDS:
            if starter["url"] not in known:
                clean.append({"url": starter["url"], "title": starter["title"]})
    if not clean:
        clean = [{"url": feed["url"], "title": feed["title"]}
                 for feed in STARTER_FEEDS]
    limit = data.get("max_posts", DEFAULT_LIMIT)
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        limit = DEFAULT_LIMIT
    return {"max_posts": limit, "feeds": clean,
            "starter_feeds_version": STARTER_FEEDS_VERSION}


def save_config(config):
    atomic_json(FEEDS_PATH, config)


def load_cache():
    data = load_json(CACHE_PATH, {"posts": []})
    posts = data.get("posts", []) if isinstance(data, dict) else []
    posts = [item for item in posts if isinstance(item, dict)]
    migrated = False
    for post in posts:
        if post.get("body"):
            save_article(post, post["body"])
            del post["body"]
            migrated = True
    if migrated:
        atomic_json(CACHE_PATH, {"posts": posts})
        gc.collect()
    return posts


def stable_id(identity):
    first = 0x1234
    second = 0x5678
    for character in str(identity or ""):
        code = ord(character)
        first = ((first * 33) + code) & 0xffff
        second = ((second * 131) ^ code) & 0xffff
    return "{:04x}{:04x}".format(first, second)


def feed_directory(post):
    return BODY_DIR + "/" + stable_id(post.get("feed_url", ""))


def article_path(post):
    identity = post.get("id") or post.get("link") or post.get("title", "")
    return feed_directory(post) + "/" + stable_id(identity) + ".txt"


def save_article(post, body):
    if not body:
        return
    try:
        solaros.storage.mkdir(feed_directory(post))
    except OSError:
        pass
    path = article_path(post)
    temporary = path + ".tmp"
    with open(temporary, "w") as output:
        output.write(body[:ARTICLE_LIMIT])
        output.flush()
    try:
        solaros.storage.remove(path)
    except OSError:
        pass
    solaros.storage.rename(temporary, path)


def remove_article(post):
    try:
        solaros.storage.remove(article_path(post))
    except OSError:
        pass


def load_article(post):
    try:
        with open(article_path(post), "r") as source:
            return source.read(ARTICLE_LIMIT)
    except Exception:
        return post.get("summary") or "No readable content."


def decode_entities(text):
    named = {"amp": "&", "lt": "<", "gt": ">", "quot": '"',
             "apos": "'", "nbsp": " ", "lsquo": "'", "rsquo": "'",
             "ldquo": '"', "rdquo": '"', "ndash": "-", "mdash": "--",
             "hellip": "..."}
    punctuation = {160: " ", 8216: "'", 8217: "'", 8220: '"',
                   8221: '"', 8211: "-", 8212: "--", 8230: "..."}
    result = []
    position = 0
    while position < len(text):
        if text[position] != "&":
            result.append(text[position])
            position += 1
            continue
        end = text.find(";", position + 1, position + 14)
        if end < 0:
            result.append("&")
            position += 1
            continue
        name = text[position + 1:end]
        value = named.get(name)
        if value is None and name.startswith("#"):
            try:
                number = int(name[2:], 16) if name.startswith("#x") else int(name[1:])
                value = punctuation.get(number)
                if value is None:
                    value = chr(number)
            except Exception:
                value = None
        if value is None:
            result.append(text[position:end + 1])
        else:
            result.append(value)
        position = end + 1
    return "".join(result)


def attribute(tag, name):
    lowered = tag.lower()
    position = 0
    wanted = name.lower()
    while True:
        start = lowered.find(wanted, position)
        if start < 0:
            return ""
        before = lowered[start - 1] if start else " "
        after_at = start + len(wanted)
        after = lowered[after_at] if after_at < len(tag) else " "
        if (before.isspace() or before == "<") and (after.isspace() or after == "="):
            break
        position = after_at
    start = after_at
    while start < len(tag) and tag[start].isspace():
        start += 1
    if start >= len(tag) or tag[start] != "=":
        return ""
    start += 1
    while start < len(tag) and tag[start].isspace():
        start += 1
    if start >= len(tag):
        return ""
    quote_char = tag[start]
    if quote_char == '"' or quote_char == "'":
        end = tag.find(quote_char, start + 1)
        return tag[start + 1:end] if end >= 0 else ""
    end = start
    while end < len(tag) and not tag[end].isspace() and tag[end] != ">":
        end += 1
    return tag[start:end]


def image_label(tag):
    alt = clean_space(decode_entities(attribute(tag, "alt")))
    source = attribute(tag, "src")
    if alt:
        return "\n[Image: " + alt + "]\n"
    if source:
        filename = source.split("?")[0].rstrip("/").split("/")[-1]
        if filename:
            return "\n[Image: " + filename + "]\n"
    return ""


def html_to_text(html):
    html = html.replace("<![CDATA[", "").replace("]]>", "")
    result = []
    position = 0
    hidden = None
    while position < len(html):
        if html[position] != "<":
            if hidden is None:
                result.append(html[position])
            position += 1
            continue
        end = html.find(">", position + 1)
        if end < 0:
            break
        tag = html[position:end + 1]
        lower = tag.lower()
        if lower.startswith("<script"):
            hidden = "script"
        elif lower.startswith("<style"):
            hidden = "style"
        elif hidden and lower.startswith("</" + hidden):
            hidden = None
        elif hidden is None:
            if lower.startswith("<img"):
                result.append(image_label(tag))
            elif lower.startswith("<li"):
                result.append("\n* ")
            elif (lower.startswith("<br") or lower.startswith("</p") or
                  lower.startswith("</div") or lower.startswith("</h") or
                  lower.startswith("</ul") or lower.startswith("</ol") or
                  lower.startswith("<hr")):
                result.append("\n")
        position = end + 1
    lines = []
    for line in decode_entities("".join(result)).replace("\xa0", " ").split("\n"):
        line = clean_space(line)
        if line:
            lines.append(line)
        elif lines and lines[-1] != "":
            lines.append("")
    return "\n".join(lines).strip()


def markdown_to_text(text):
    # Small readable subset: headings, emphasis, links, and images.
    lines = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        while line.startswith("#"):
            line = line[1:].lstrip()
        line = line.replace("**", "").replace("__", "").replace("`", "")
        position = 0
        output = ""
        while position < len(line):
            image = line.find("![", position)
            link = line.find("[", position)
            start = image if image >= 0 and (link < 0 or image <= link) else link
            if start < 0:
                output += line[position:]
                break
            output += line[position:start]
            label_start = start + (2 if start == image else 1)
            label_end = line.find("](", label_start)
            url_end = line.find(")", label_end + 2) if label_end >= 0 else -1
            if label_end < 0 or url_end < 0:
                output += line[start:]
                break
            label = line[label_start:label_end]
            url = line[label_end + 2:url_end]
            if start == image:
                fallback = url.split("?")[0].split("/")[-1]
                output += "[Image: " + (label or fallback) + "]"
            else:
                output += label
            position = url_end + 1
        lines.append(output)
    return "\n".join(lines).strip()


def rendered_text(value):
    value = value or ""
    rendered = (html_to_text(value) if "<" in value and ">" in value
                else markdown_to_text(value))
    # A second bounded pass handles common double-escaped feed content such as
    # &amp;#8217; without repeatedly expanding malformed or adversarial input.
    first = decode_entities(rendered)
    return decode_entities(first) if "&" in first else first


def tag_value(block, names):
    lower = block.lower()
    for name in names:
        marker = "<" + name.lower()
        start = lower.find(marker)
        if start < 0:
            continue
        open_end = lower.find(">", start)
        close = lower.find("</" + name.lower() + ">", open_end + 1)
        if open_end >= 0 and close >= 0:
            return block[open_end + 1:close].strip()
    return ""


def atom_link(block):
    lower = block.lower()
    position = 0
    while True:
        start = lower.find("<link", position)
        if start < 0:
            return ""
        end = lower.find(">", start)
        if end < 0:
            return ""
        tag = block[start:end + 1]
        relation = attribute(tag, "rel")
        href = attribute(tag, "href")
        if href and (not relation or relation == "alternate"):
            return decode_entities(href)
        position = end + 1


def split_entries(xml):
    lower = xml.lower()
    element = "item" if "<item" in lower else "entry"
    result = []
    position = 0
    while True:
        start = lower.find("<" + element, position)
        if start < 0:
            break
        start = lower.find(">", start)
        end = lower.find("</" + element + ">", start + 1)
        if start < 0 or end < 0:
            break
        result.append(xml[start + 1:end])
        position = end + len(element) + 3
    return result, element


def first_sentence(text):
    text = clean_space(text)
    for marker in (". ", "! ", "? "):
        end = text.find(marker)
        if end >= 0 and end < 220:
            return text[:end + 1]
    return text[:220]


def ascii_digits(value):
    if not value:
        return False
    for character in value:
        if character < "0" or character > "9":
            return False
    return True


def parse_feed(xml, feed_url, fallback_title):
    entries, kind = split_entries(xml)
    channel_end = xml.lower().find("<item")
    if channel_end < 0:
        channel_end = xml.lower().find("<entry")
    header = xml[:channel_end] if channel_end >= 0 else xml
    feed_title = rendered_text(tag_value(header, ("title",))) or fallback_title or feed_url
    posts = [parse_entry(block, kind, feed_url, feed_title)
             for block in entries]
    return feed_title, posts


def parse_entry(block, kind, feed_url, feed_title):
    title = rendered_text(tag_value(block, ("title",)))
    link = tag_value(block, ("link", "guid"))
    if kind == "entry":
        link = atom_link(block) or link
    body_raw = tag_value(block, ("content:encoded", "content", "description", "summary"))
    summary_raw = tag_value(block, ("description", "summary"))
    body = rendered_text(body_raw)[:ARTICLE_LIMIT]
    summary = rendered_text(summary_raw)[:512]
    date = clean_space(decode_entities(tag_value(
        block, ("pubDate", "published", "updated", "dc:date"))))
    identity = tag_value(block, ("guid", "id")) or link or title
    return {
        "id": clean_space(decode_entities(identity)),
        "feed_url": feed_url,
        "feed_title": feed_title,
        "title": title or first_sentence(body or summary),
        "link": clean_space(decode_entities(link)),
        "date": date,
        "body": body or summary,
        "summary": summary or first_sentence(body),
    }


def decode_chunk(pending, chunk):
    data = pending + chunk
    for tail in range(0, min(4, len(data) + 1)):
        try:
            end = len(data) - tail
            return data[:end].decode("utf-8"), data[end:]
        except UnicodeError:
            pass
    return data.decode("utf-8", "replace"), b""


def fetch_feed_stream(feed, limit):
    headers = {"Accept": "application/rss+xml, application/atom+xml, text/xml"}
    handle = solaros.http.stream_open("GET", feed["url"], None, headers, 20000, False)
    received = 0
    status = 0
    try:
        with open(FEED_TEMP, "wb") as output:
            while not solaros.should_exit():
                event = solaros.http.stream_read(handle, 1000)
                if event is None:
                    continue
                event_type = event.get("type")
                if event_type == "response":
                    status = event.get("status_code", 0)
                    if status < 200 or status >= 300:
                        raise RuntimeError("HTTP {}".format(status))
                elif event_type == "data":
                    chunk = event.get("data", b"")
                    received += len(chunk)
                    if received > HTTP_LIMIT:
                        raise RuntimeError("feed exceeds 256 KB")
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
        return parse_feed_file(FEED_TEMP, feed, limit)
    finally:
        try:
            solaros.storage.remove(FEED_TEMP)
        except OSError:
            pass
        gc.collect()


def parse_feed_file(path, feed, limit):
    buffer = bytearray()
    lowered = bytearray()
    kind = None
    feed_title = feed.get("title", "") or feed["url"]
    posts = []
    with open(path, "rb") as source:
        while not solaros.should_exit() and len(posts) < limit:
            chunk = source.read(2048)
            if not chunk:
                break
            buffer.extend(chunk)
            lowered.extend(chunk.lower())
            if kind is None:
                item_at = lowered.find(b"<item")
                entry_at = lowered.find(b"<entry")
                candidates = [value for value in (item_at, entry_at) if value >= 0]
                if not candidates:
                    if len(buffer) > 16384:
                        buffer = buffer[-16384:]
                        lowered = lowered[-16384:]
                    continue
                first = min(candidates)
                kind = "item" if first == item_at else "entry"
                header, unused = decode_chunk(b"", bytes(buffer[:first]))
                feed_title = (rendered_text(tag_value(header, ("title",))) or
                              feed_title)
                buffer = buffer[first:]
                lowered = lowered[first:]
            opening = ("<" + kind).encode("ascii")
            closing = ("</" + kind + ">").encode("ascii")
            while len(posts) < limit:
                start = lowered.find(opening)
                if start < 0:
                    if len(buffer) > 32:
                        buffer = buffer[-32:]
                        lowered = lowered[-32:]
                    break
                open_end = lowered.find(b">", start)
                end = lowered.find(closing, open_end + 1)
                if open_end < 0 or end < 0:
                    if start > 0:
                        buffer = buffer[start:]
                        lowered = lowered[start:]
                    if len(buffer) > ENTRY_BUFFER_LIMIT:
                        raise RuntimeError("feed entry is too large")
                    break
                block, unused = decode_chunk(
                    b"", bytes(buffer[open_end + 1:end]))
                post = parse_entry(block, kind, feed["url"], feed_title)
                save_article(post, post.get("body", ""))
                if "body" in post:
                    del post["body"]
                posts.append(post)
                consumed = end + len(closing)
                buffer = buffer[consumed:]
                lowered = lowered[consumed:]
                block = None
                if len(posts) % 4 == 0:
                    gc.collect()
    if not posts:
        raise RuntimeError("feed contains no readable posts")
    return feed_title, posts


def date_key(value):
    months = {"jan": "01", "feb": "02", "mar": "03", "apr": "04",
              "may": "05", "jun": "06", "jul": "07", "aug": "08",
              "sep": "09", "oct": "10", "nov": "11", "dec": "12"}
    value = clean_space(value).lower().replace(",", "")
    if len(value) >= 10 and value[4:5] == "-":
        digits = "".join(ch for ch in value[:19] if "0" <= ch <= "9")
        return (digits + "00000000000000")[:14]
    parts = value.split()
    for index, part in enumerate(parts):
        if len(part) == 4 and ascii_digits(part) and index >= 2:
            day = ("0" + parts[index - 2])[-2:]
            month = months.get(parts[index - 1][:3], "00")
            clock = parts[index + 1].replace(":", "") if index + 1 < len(parts) else ""
            return part + month + day + (clock + "000000")[:6]
    return value


def short_date(value):
    months = {"jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr",
              "may": "May", "jun": "Jun", "jul": "Jul", "aug": "Aug",
              "sep": "Sep", "oct": "Oct", "nov": "Nov", "dec": "Dec"}
    value = clean_space(value)
    if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        try:
            return month_names[int(value[5:7]) - 1] + " " + str(int(value[8:10]))
        except Exception:
            return value[:10]
    parts = value.replace(",", "").split()
    for index, part in enumerate(parts):
        month = months.get(part[:3].lower())
        if month and index + 1 < len(parts):
            try:
                return month + " " + str(int(parts[index + 1]))
            except Exception:
                pass
    return clip(value, 10)


def refresh(config, old_posts):
    retained = list(old_posts)
    errors = []
    for number, feed in enumerate(config["feeds"]):
        gc.collect()
        show_message("RSS refresh", "Fetching {} of {}\n{}".format(
            number + 1, len(config["feeds"]), feed.get("title") or feed["url"]),
            "Please wait")
        try:
            title, fresh = fetch_feed_stream(feed, config["max_posts"])
            feed["title"] = title
            old_for_feed = [post for post in retained if post.get("feed_url") == feed["url"]]
            old_by_id = {}
            for post in old_for_feed:
                identity = post.get("id") or post.get("link") or post.get("title")
                if identity:
                    old_by_id[identity] = post
            for post in fresh:
                identity = post.get("id") or post.get("link") or post.get("title")
                if identity in old_by_id and old_by_id[identity].get("read"):
                    post["read"] = True
            by_id = {}
            for post in fresh + old_for_feed:
                identity = post.get("id") or post.get("link") or post.get("title")
                if identity and identity not in by_id:
                    by_id[identity] = post
            merged = list(by_id.values())
            merged.sort(key=lambda post: date_key(post.get("date", "")), reverse=True)
            merged = merged[:config["max_posts"]]
            kept_paths = set(article_path(post) for post in merged)
            for post in fresh + old_for_feed:
                if article_path(post) not in kept_paths:
                    remove_article(post)
            retained = [post for post in retained if post.get("feed_url") != feed["url"]]
            retained.extend(merged)
            atomic_json(CACHE_PATH, {"posts": retained})
            fresh = None
            old_for_feed = None
            old_by_id = None
            by_id = None
            merged = None
            gc.collect()
        except Exception as error:
            errors.append((feed.get("title") or feed["url"]) + ": " + str(error))
    retained.sort(key=lambda post: date_key(post.get("date", "")), reverse=True)
    atomic_json(CACHE_PATH, {"posts": retained})
    save_config(config)
    return retained, errors


def filtered_posts(posts, feed_url):
    if not feed_url:
        return posts
    return [post for post in posts if post.get("feed_url") == feed_url]


def draw_posts(posts, selected, view_name, note="", individual=False):
    rows, cols = tui.size()
    tui.clear()
    heading = " RSS: " + view_name + " "
    if note:
        heading += "| " + note + " "
    tui.addstr(0, 0, clip(heading, cols), tui.INVERSE)
    item_height = 2 if individual else 3
    visible = max(1, (rows - 2) // item_height)
    start = (selected // visible) * visible
    row = 1
    for index in range(start, min(len(posts), start + visible)):
        post = posts[index]
        prefix = "> " if index == selected else "  "
        attr = 0 if post.get("read") else tui.BOLD
        if index == selected:
            attr |= tui.INVERSE
        if individual:
            date = short_date(post.get("date", ""))
            title_width = max(1, cols - len(date) - 3) if date else cols
            tui.addstr(row, 0, clip(prefix + post.get("title", "Untitled"),
                                    title_width), attr)
            if date:
                tui.addstr(row, cols - len(date), date)
            tui.addstr(row + 1, 0, "-" * cols)
        else:
            tui.addstr(row, 0, clip(prefix + post.get("title", "Untitled"), cols), attr)
            meta = post.get("feed_title", "")
            if post.get("date"):
                meta += "  " + post["date"]
            tui.addstr(row + 1, 3, clip(meta, cols - 3))
            tui.addstr(row + 2, 0, "-" * cols)
        row += item_height
    if not posts:
        tui.addstr(3, 2, "No cached posts. Press r to refresh.")
    footer = "Up/Down Enter read  f feeds  r refresh  q quit"
    if individual:
        footer = "Up/Down Enter read  m mark all read  f feeds  q quit"
    tui.addstr(rows - 1, 0,
               clip(footer, cols),
               tui.INVERSE)
    tui.refresh()


def show_post(post):
    rows, cols = tui.size()
    content = load_article(post)
    lines = wrap(content, cols - 2)
    offset = 0
    dirty = True
    while not solaros.should_exit():
        if dirty:
            tui.clear()
            tui.addstr(0, 0, clip(" " + post.get("title", "Untitled") + " ", cols),
                       tui.INVERSE)
            row = 1
            for line in lines[offset:offset + rows - 3]:
                tui.addstr(row, 1, line)
                row += 1
            position = "{}-{} / {}".format(offset + 1,
                min(len(lines), offset + rows - 3), len(lines))
            tui.addstr(rows - 2, 1, clip(position + "  " + post.get("link", ""), cols - 2))
            tui.addstr(rows - 1, 0,
                       clip("Up/Down PgUp/PgDn scroll  Esc back", cols), tui.INVERSE)
            tui.refresh()
            dirty = False
        key = tui.getch(250)
        maximum = max(0, len(lines) - (rows - 3))
        if key == tui.KEY_ESCAPE or key == tui.KEY_LEFT or key == ord("q"):
            return
        if key == tui.KEY_DOWN and offset < maximum:
            offset += 1
            dirty = True
        elif key == tui.KEY_UP and offset > 0:
            offset -= 1
            dirty = True
        elif key == tui.KEY_PAGE_DOWN:
            offset = min(maximum, offset + rows - 4)
            dirty = True
        elif key == tui.KEY_PAGE_UP:
            offset = max(0, offset - rows + 4)
            dirty = True
        elif key == tui.KEY_HOME:
            offset = 0
            dirty = True
        elif key == tui.KEY_END:
            offset = maximum
            dirty = True


def draw_feeds(config, selected, note=""):
    rows, cols = tui.size()
    tui.clear()
    title = " Feeds " + (("| " + note + " ") if note else "")
    tui.addstr(0, 0, clip(title, cols), tui.INVERSE)
    items = [{"title": "All feeds", "url": ""}] + config["feeds"]
    visible = max(1, rows - 3)
    start = (selected // visible) * visible
    row = 2
    for index in range(start, min(len(items), start + visible)):
        item = items[index]
        prefix = "> " if index == selected else "  "
        attr = tui.INVERSE if index == selected else tui.BOLD
        tui.addstr(row, 0, clip(prefix + (item.get("title") or item["url"]), cols), attr)
        row += 1
    tui.addstr(rows - 2, 1, "Cache limit: {} posts per feed".format(config["max_posts"]))
    tui.addstr(rows - 1, 0,
               clip("Enter view  a add  x remove  +/- limit  Esc back", cols),
               tui.INVERSE)
    tui.refresh()


def manage_feeds(config):
    selected = 0
    note = ""
    dirty = True
    while not solaros.should_exit():
        items = [{"title": "All feeds", "url": ""}] + config["feeds"]
        if dirty:
            draw_feeds(config, selected, note)
            note = ""
            dirty = False
        key = tui.getch(250)
        if key is None:
            continue
        if key == tui.KEY_ESCAPE or key == tui.KEY_LEFT or key == ord("q"):
            return None
        if key == tui.KEY_DOWN and selected + 1 < len(items):
            selected += 1
            dirty = True
        elif key == tui.KEY_UP and selected > 0:
            selected -= 1
            dirty = True
        elif key == KEY_ENTER or key == KEY_RETURN or key == tui.KEY_RIGHT:
            return items[selected]
        elif key == ord("a"):
            url = edit_text("Add feed", "HTTPS feed URL")
            if url:
                if not url.startswith("https://"):
                    note = "URL must start with https://"
                elif any(feed["url"] == url for feed in config["feeds"]):
                    note = "already added"
                else:
                    config["feeds"].append({"url": url, "title": ""})
                    save_config(config)
                    selected = len(config["feeds"])
                    note = "added; refresh to download"
            dirty = True
        elif key == ord("x") and selected > 0:
            feed = config["feeds"][selected - 1]
            show_message("Remove feed?", feed.get("title") or feed["url"],
                         "y remove  any other key cancels")
            if wait_key() == ord("y"):
                config["feeds"].pop(selected - 1)
                save_config(config)
                selected = min(selected, len(config["feeds"]))
                note = "removed (cached posts retained)"
            dirty = True
        elif key == ord("+") and config["max_posts"] < 50:
            config["max_posts"] += 1
            save_config(config)
            dirty = True
        elif key == ord("-") and config["max_posts"] > 1:
            config["max_posts"] -= 1
            save_config(config)
            dirty = True


def main():
    try:
        try:
            solaros.storage.mkdir(APP_DIR)
        except OSError:
            pass
        try:
            solaros.storage.mkdir(BODY_DIR)
        except OSError:
            pass
        config = load_config()
        save_config(config)
        posts = load_cache()
        feed_url = ""
        view_name = "All feeds"
        selected = 0
        note = "offline cache" if posts else "press r to download"
        dirty = True
        while not solaros.should_exit():
            shown = filtered_posts(posts, feed_url)
            if dirty:
                draw_posts(shown, selected, view_name, note, bool(feed_url))
                note = ""
                dirty = False
            key = tui.getch(250)
            if key is None:
                continue
            if key == tui.KEY_ESCAPE or key == ord("q"):
                break
            if key == tui.KEY_DOWN and selected + 1 < len(shown):
                selected += 1
                dirty = True
            elif key == tui.KEY_UP and selected > 0:
                selected -= 1
                dirty = True
            elif key == tui.KEY_PAGE_DOWN and shown:
                selected = min(len(shown) - 1, selected + 5)
                dirty = True
            elif key == tui.KEY_PAGE_UP:
                selected = max(0, selected - 5)
                dirty = True
            elif (key == KEY_ENTER or key == KEY_RETURN or key == tui.KEY_RIGHT) and shown:
                shown[selected]["read"] = True
                atomic_json(CACHE_PATH, {"posts": posts})
                show_post(shown[selected])
                dirty = True
            elif key == ord("m") and feed_url:
                for post in posts:
                    if post.get("feed_url") == feed_url:
                        post["read"] = True
                atomic_json(CACHE_PATH, {"posts": posts})
                note = "all marked read"
                dirty = True
            elif key == ord("f"):
                choice = manage_feeds(config)
                if choice is not None:
                    feed_url = choice.get("url", "")
                    view_name = choice.get("title") or "All feeds"
                    selected = 0
                dirty = True
            elif key == ord("r"):
                posts, errors = refresh(config, posts)
                shown = filtered_posts(posts, feed_url)
                selected = min(selected, max(0, len(shown) - 1))
                note = "{} cached".format(len(posts))
                if errors:
                    note += "; {} failed".format(len(errors))
                    show_message("Refresh finished", "\n".join(errors), "Press any key")
                    wait_key()
                dirty = True
    except KeyboardInterrupt:
        pass
    except Exception as error:
        show_message("RSS error", str(error), "Press any key")
        wait_key()
    finally:
        tui.clear()
        tui.refresh()


if __name__ == "__main__":
    main()

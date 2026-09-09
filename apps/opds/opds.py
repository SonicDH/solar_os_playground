"""Small multi-server OPDS browser and downloader for SolarOS."""

import binascii
import gc
import json
import sys

import solaros
from solaros import tui


def app_directory():
    path = sys.argv[0] if sys.argv else "opds.py"
    if not path or "/" not in path:
        try:
            path = __file__
        except NameError:
            path = "opds.py"
    separator = path.rfind("/")
    if separator < 0:
        return "."
    return path[:separator] if separator > 0 else "/"


APP_DIR = app_directory()
SERVERS_PATH = APP_DIR + "/servers.json"
READING_PATH = APP_DIR + "/to-read.json"
DOWNLOADS_PATH = APP_DIR + "/downloads.json"
TEMP_PATH = APP_DIR + "/response.tmp"
CACHE_DIR = APP_DIR + "/cache"
BOOK_DIR = "/Books"
FEED_LIMIT = 512 * 1024
BOOK_LIMIT = 64 * 1024 * 1024
SUMMARY_LIMIT = 2048
SUMMARY_SOURCE_LIMIT = 8192
SEARCH_DESCRIPTOR_LIMIT = 32768
ENTRY_LIMIT = 100
ENTRY_BUFFER_LIMIT = 48 * 1024
HEADER_BUFFER_LIMIT = 16 * 1024
PROGRESS_STEP = 4 * 1024
CACHE_TTL_MS = 3 * 60 * 1000
CACHE_SLOTS = 8

_feed_cache = {}
_cache_order = []
_pending_key = None

KEY_ENTER = 10
KEY_RETURN = 13
KEY_BACKSPACE = 8
KEY_DELETE_CHAR = 127

SUPPORTED_TYPES = {
    "application/epub+zip": ".epub",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
}
SUPPORTED_EXTENSIONS = (".epub", ".txt", ".text", ".md", ".markdown")


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
    lines = []
    for paragraph in str(value or "").replace("\r", "").split("\n"):
        paragraph = clean_space(paragraph)
        if not paragraph:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        while len(paragraph) > width:
            cut = paragraph.rfind(" ", 0, width + 1)
            if cut < 1:
                cut = width
            lines.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        lines.append(paragraph)
    return lines or [""]


def message(title, body, footer="Press any key"):
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


def prefetch_input_waiting():
    global _pending_key
    key = tui.getch(0)
    if key is None:
        return False
    _pending_key = key
    return True


def edit_text(title, label, initial="", max_length=512, secret=False):
    value = initial
    dirty = True
    while not solaros.should_exit():
        if dirty:
            rows, cols = tui.size()
            tui.clear()
            tui.addstr(0, 0, clip(" " + title + " ", cols), tui.INVERSE)
            tui.addstr(2, 1, clip(label, cols - 2), tui.BOLD)
            shown = "*" * len(value) if secret else value
            row = 4
            for line in wrap(shown, cols - 2)[-max(1, rows - 6):]:
                tui.addstr(row, 1, line)
                row += 1
            tui.addstr(rows - 1, 0, clip("Enter accept  Esc cancel", cols), tui.INVERSE)
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


def ensure_dir(path):
    try:
        solaros.storage.mkdir(path)
    except OSError:
        pass


def remove_if_present(path):
    try:
        solaros.storage.remove(path)
    except OSError:
        pass


def load_json(path, fallback):
    try:
        with open(path, "r") as source:
            return json.load(source)
    except Exception:
        return fallback


def save_json(path, value):
    temporary = path + ".tmp"
    with open(temporary, "w") as output:
        json.dump(value, output)
        output.flush()
    remove_if_present(path)
    solaros.storage.rename(temporary, path)
    gc.collect()


def stable_id(identity):
    first = 0x1234
    second = 0x5678
    for character in str(identity or ""):
        code = ord(character)
        first = ((first * 33) + code) & 0xffff
        second = ((second * 131) ^ code) & 0xffff
    return "{:04x}{:04x}".format(first, second)


def load_servers():
    value = load_json(SERVERS_PATH, {"servers": []})
    servers = value.get("servers", []) if isinstance(value, dict) else []
    clean = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        url = server.get("url", "")
        if not isinstance(url, str) or not url:
            continue
        clean.append({
            "id": str(server.get("id") or stable_id(url)),
            "name": clean_space(server.get("name")) or "OPDS server",
            "url": url,
            "key": str(server.get("key") or ""),
            "username": str(server.get("username") or ""),
            "password": str(server.get("password") or ""),
        })
    return clean


def load_records(path):
    value = load_json(path, {"items": []})
    items = value.get("items", []) if isinstance(value, dict) else []
    return [item for item in items if isinstance(item, dict)]


def save_records(path, items):
    save_json(path, {"items": items})


def server_catalog_url(server):
    url = server["url"].rstrip("/")
    key = server.get("key", "")
    if key and "/api/opds/" not in url:
        return url + "/api/opds/" + key
    return url


def origin(url):
    marker = url.find("://")
    if marker < 0:
        return ""
    end = url.find("/", marker + 3)
    return url if end < 0 else url[:end]


def resolve_url(base, href):
    href = decode_entities(href or "").strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href
    root = origin(base)
    if href.startswith("/"):
        return root + href
    base_without_fragment = base.split("#")[0]
    if href.startswith("?"):
        return base_without_fragment.split("?")[0] + href
    base_without_query = base_without_fragment.split("?")[0]
    slash = base_without_query.rfind("/")
    return base_without_query[:slash + 1] + href


def request_headers(server, accept):
    headers = {"Accept": accept}
    username = server.get("username", "")
    if username:
        raw = (username + ":" + server.get("password", "")).encode("utf-8")
        token = binascii.b2a_base64(raw).decode("ascii").strip()
        headers["Authorization"] = "Basic " + token
    return headers


def draw_progress(label, received, total=-1):
    if total and total > 0:
        percent = min(100, (received * 100) // total)
        filled = min(20, (percent * 20) // 100)
        bar = "[" + ("#" * filled) + ("-" * (20 - filled)) + "]"
        body = "{}\n\n{}%  {} / {} KB".format(
            bar, percent, received // 1024, (total + 1023) // 1024)
    else:
        body = "{} KB received".format(received // 1024)
    message(label, body, "Please wait")


def stream_download(url, path, server, accept, max_bytes, follow_redirects=False,
                    progress_label="Receiving", show_progress=True,
                    cancel_on_input=False):
    handle = solaros.http.stream_open(
        "GET", url, None, request_headers(server, accept), 30000, follow_redirects)
    status = 0
    received = 0
    content_length = -1
    next_progress = 0
    try:
        with open(path, "wb") as output:
            while not solaros.should_exit():
                if cancel_on_input and prefetch_input_waiting():
                    raise RuntimeError("prefetch cancelled")
                event = solaros.http.stream_read(handle, 100 if cancel_on_input else 1000)
                if event is None:
                    continue
                kind = event.get("type")
                if kind == "response":
                    status = event.get("status_code", 0)
                    if status < 200 or status >= 300:
                        raise RuntimeError("HTTP {}".format(status))
                    content_length = event.get("content_length", -1)
                    if show_progress:
                        draw_progress(progress_label, 0, content_length)
                elif kind == "data":
                    chunk = event.get("data", b"")
                    received += len(chunk)
                    if received > max_bytes:
                        raise RuntimeError("download exceeds size limit")
                    output.write(chunk)
                    if show_progress and received >= next_progress:
                        draw_progress(progress_label, received, content_length)
                        if content_length > 0:
                            next_progress = received + max(
                                PROGRESS_STEP, content_length // 20)
                        else:
                            next_progress = received + PROGRESS_STEP
                elif kind == "error":
                    raise RuntimeError(event.get("error_name", "HTTP stream error"))
                elif kind == "complete":
                    if show_progress:
                        draw_progress(progress_label, received,
                                      content_length if content_length > 0 else received)
                    break
            output.flush()
    finally:
        solaros.http.stream_close(handle)
        gc.collect()
    if status < 200 or status >= 300:
        raise RuntimeError("HTTP {}".format(status or "request failed"))
    return received


def decode_entities(text):
    named = {"amp": "&", "lt": "<", "gt": ">", "quot": '"',
             "apos": "'", "nbsp": " "}
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
                value = chr(number)
            except Exception:
                value = None
        result.append(value if value is not None else text[position:end + 1])
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
    quote = tag[start]
    if quote == '"' or quote == "'":
        end = tag.find(quote, start + 1)
        return tag[start + 1:end] if end >= 0 else ""
    end = start
    while end < len(tag) and not tag[end].isspace() and tag[end] != ">":
        end += 1
    return tag[start:end]


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


def strip_markup(value):
    value = decode_entities(value.replace("<![CDATA[", "").replace("]]>", ""))
    output = []
    position = 0
    while position < len(value):
        if value[position] != "<":
            output.append(value[position])
            position += 1
            continue
        end = value.find(">", position + 1)
        if end < 0:
            break
        tag = value[position + 1:end].lower()
        if tag.startswith("br") or tag.startswith("/p") or tag.startswith("/div"):
            output.append("\n")
        position = end + 1
    return decode_entities("".join(output)).strip()


def link_tags(block):
    lower = block.lower()
    links = []
    position = 0
    while True:
        start = lower.find("<link", position)
        if start < 0:
            return links
        end = lower.find(">", start)
        if end < 0:
            return links
        links.append(block[start:end + 1])
        position = end + 1


def extension_for(link_type, href):
    media_type = (link_type or "").split(";")[0].strip().lower()
    extension = SUPPORTED_TYPES.get(media_type)
    if extension:
        return extension
    path = (href or "").split("?")[0].lower()
    if media_type in ("", "application/octet-stream"):
        for candidate in SUPPORTED_EXTENSIONS:
            if path.endswith(candidate):
                return ".txt" if candidate == ".text" else ".md" if candidate == ".markdown" else candidate
    return ""


def navigation_format_supported(summary):
    """Filter Kavita's typed series rows while retaining generic OPDS folders."""
    value = clean_space(summary).lower()
    if not value.startswith("format:"):
        return True
    kind = value[7:].strip().split(" ")[0].strip(".,;")
    return kind in ("epub", "text", "txt", "markdown", "md")


def parse_entry(block, feed_url):
    title = clean_space(strip_markup(tag_value(block, ("title",)))) or "Untitled"
    identity = clean_space(decode_entities(tag_value(block, ("id",))))
    summary_source = tag_value(block, ("summary", "content"))
    summary = strip_markup(summary_source[:SUMMARY_SOURCE_LIMIT])[:SUMMARY_LIMIT]
    author_block = tag_value(block, ("author",))
    author = clean_space(strip_markup(tag_value(author_block, ("name",))))
    if not author:
        author = clean_space(strip_markup(tag_value(block, ("dc:creator",))))
    navigation = ""
    acquisition = ""
    extension = ""
    media_type = ""
    has_acquisition = False
    for tag in link_tags(block):
        relation = decode_entities(attribute(tag, "rel")).lower()
        href = decode_entities(attribute(tag, "href"))
        kind = decode_entities(attribute(tag, "type"))
        if relation.startswith("http://opds-spec.org/acquisition"):
            has_acquisition = True
            candidate = extension_for(kind, href)
            if candidate and not acquisition:
                acquisition = resolve_url(feed_url, href)
                extension = candidate
                media_type = kind
        elif relation in ("subsection", "alternate", "collection") and href:
            if "atom+xml" in kind.lower() or relation == "subsection":
                navigation = resolve_url(feed_url, href)
    if acquisition:
        return {"kind": "book", "id": identity or acquisition, "title": title,
                "author": author, "summary": summary, "url": acquisition,
                "extension": extension, "media_type": media_type}
    if navigation and not has_acquisition and navigation_format_supported(summary):
        return {"kind": "navigation", "id": identity or navigation,
                "title": title, "summary": summary, "url": navigation}
    return None


def parse_feed_file(path, feed_url, cancel_on_input=False):
    title = "OPDS"
    next_url = ""
    search_url = ""
    items = []
    positions = {}
    buffer = ""
    header_done = False
    with open(path, "r") as source:
        while len(items) < ENTRY_LIMIT:
            if cancel_on_input and prefetch_input_waiting():
                raise RuntimeError("prefetch cancelled")
            chunk = source.read(1024)
            if not chunk:
                break
            buffer += chunk
            lower = buffer.lower()
            if not header_done:
                first_entry = lower.find("<entry")
                if first_entry < 0:
                    if len(buffer) > HEADER_BUFFER_LIMIT:
                        raise RuntimeError("catalog header is too large")
                    continue
                header = buffer[:first_entry]
                title = clean_space(strip_markup(tag_value(header, ("title",)))) or "OPDS"
                for tag in link_tags(header):
                    relation = decode_entities(attribute(tag, "rel")).lower()
                    href = decode_entities(attribute(tag, "href"))
                    if relation == "next" and href:
                        next_url = resolve_url(feed_url, href)
                    elif relation == "search" and href:
                        search_url = resolve_url(feed_url, href)
                buffer = buffer[first_entry:]
                lower = buffer.lower()
                header_done = True
            while len(items) < ENTRY_LIMIT:
                start = lower.find("<entry")
                if start < 0:
                    buffer = buffer[-32:]
                    break
                open_end = lower.find(">", start)
                end = lower.find("</entry>", open_end + 1)
                if open_end < 0 or end < 0:
                    if start > 0:
                        buffer = buffer[start:]
                    if len(buffer) > ENTRY_BUFFER_LIMIT:
                        raise RuntimeError("catalog entry is too large")
                    break
                item = parse_entry(buffer[open_end + 1:end], feed_url)
                if item:
                    identity = item.get("kind", "") + "\n" + item.get("id", "")
                    old_at = positions.get(identity)
                    if old_at is None:
                        positions[identity] = len(items)
                        items.append(item)
                    elif items[old_at].get("title", "").startswith("Continue Reading from:"):
                        items[old_at] = item
                buffer = buffer[end + 8:]
                lower = buffer.lower()
                if len(items) % 8 == 0:
                    gc.collect()
    if not header_done and buffer:
        title = clean_space(strip_markup(tag_value(buffer, ("title",)))) or "OPDS"
    return {"title": title, "items": items, "next": next_url,
            "search": search_url}


def fetch_feed(server, url, show_status=True):
    key = server.get("id", "") + "\n" + url
    now = solaros.time.uptime_ms()
    cached = _feed_cache.get(key)
    if cached and now - cached[1] <= CACHE_TTL_MS and file_exists(cached[0]):
        parsed_path = cached[0] + ".json"
        if show_status:
            message("Loading cached catalog", "Using the recently parsed copy", "Please wait")
        parsed = load_json(parsed_path, None)
        if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
            return parsed
        if show_status:
            message("Processing catalog", "Preparing a fast return cache", "Please wait")
        parsed = parse_feed_file(cached[0], url, not show_status)
        save_json(parsed_path, parsed)
        return parsed

    ensure_dir(CACHE_DIR)
    if cached:
        cache_path = cached[0]
        try:
            _cache_order.remove(key)
        except ValueError:
            pass
    elif len(_cache_order) >= CACHE_SLOTS:
        oldest = _cache_order.pop(0)
        cache_path = _feed_cache.pop(oldest)[0]
    else:
        cache_path = CACHE_DIR + "/feed{}.xml".format(len(_cache_order))
    remove_if_present(cache_path)
    remove_if_present(cache_path + ".json")
    try:
        stream_download(url, cache_path, server,
                        "application/atom+xml;profile=opds-catalog, application/atom+xml, text/xml",
                        FEED_LIMIT, False, "Downloading catalog", show_status,
                        not show_status)
        _feed_cache[key] = (cache_path, solaros.time.uptime_ms())
        _cache_order.append(key)
        if show_status:
            message("Processing catalog", "Reading downloaded entries", "Please wait")
        parsed = parse_feed_file(cache_path, url, not show_status)
        if show_status:
            message("Caching catalog", "Saving the parsed page for quick return", "Please wait")
        save_json(cache_path + ".json", parsed)
        return parsed
    except Exception:
        remove_if_present(cache_path)
        remove_if_present(cache_path + ".json")
        raise
    finally:
        gc.collect()


def percent_encode(value):
    result = []
    for byte in value.encode("utf-8"):
        if ((48 <= byte <= 57) or (65 <= byte <= 90) or
                (97 <= byte <= 122) or byte in (45, 46, 95, 126)):
            result.append(chr(byte))
        else:
            result.append("%{:02X}".format(byte))
    return "".join(result)


def fetch_search_template(server, descriptor_url):
    remove_if_present(TEMP_PATH)
    try:
        stream_download(descriptor_url, TEMP_PATH, server,
                        "application/opensearchdescription+xml, text/xml", FEED_LIMIT)
        parts = []
        total = 0
        with open(TEMP_PATH, "r") as source:
            while True:
                chunk = source.read(1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > SEARCH_DESCRIPTOR_LIMIT:
                    raise RuntimeError("search descriptor is too large")
                parts.append(chunk)
        xml = "".join(parts)
        parts = None
        gc.collect()
        lower = xml.lower()
        position = 0
        while True:
            start = lower.find("<url", position)
            if start < 0:
                break
            end = lower.find(">", start)
            if end < 0:
                break
            tag = xml[start:end + 1]
            template = decode_entities(attribute(tag, "template"))
            kind = attribute(tag, "type").lower()
            if template and "atom+xml" in kind:
                return resolve_url(descriptor_url, template)
            position = end + 1
        raise RuntimeError("server has no OPDS search template")
    finally:
        remove_if_present(TEMP_PATH)
        gc.collect()


def record_key(server_id, entry_id):
    return str(server_id) + "\n" + str(entry_id)


def is_starred(to_read, server_id, item):
    wanted = record_key(server_id, item.get("id"))
    for record in to_read:
        if record_key(record.get("server_id"), record.get("entry_id")) == wanted:
            return True
    return False


def toggle_star(to_read, server, item):
    wanted = record_key(server["id"], item.get("id"))
    for index, record in enumerate(to_read):
        if record_key(record.get("server_id"), record.get("entry_id")) == wanted:
            del to_read[index]
            save_records(READING_PATH, to_read)
            return False
    to_read.insert(0, {
        "server_id": server["id"], "entry_id": item.get("id", ""),
        "title": item.get("title", "Untitled"), "author": item.get("author", ""),
        "summary": item.get("summary", "")[:SUMMARY_LIMIT],
        "url": item.get("url", ""), "extension": item.get("extension", ""),
        "media_type": item.get("media_type", ""),
    })
    save_records(READING_PATH, to_read)
    return True


def safe_filename(title, extension, identity):
    result = []
    separator = False
    for character in clean_space(title):
        code = ord(character)
        if ((48 <= code <= 57) or (65 <= code <= 90) or
                (97 <= code <= 122) or character in ("-", "_")):
            result.append(character)
            separator = False
        else:
            if result and not separator:
                result.append("_")
                separator = True
    stem = "".join(result).strip("_") or "book"
    stem = stem[:72].rstrip("_")
    return stem + "-" + stable_id(identity) + extension


def file_exists(path):
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


def download_book(server, item, downloads):
    ensure_dir(BOOK_DIR)
    extension = item.get("extension", "")
    if extension not in (".epub", ".txt", ".md"):
        raise RuntimeError("unsupported book format")
    identity = item.get("id") or item.get("url") or item.get("title")
    composite = record_key(server["id"], identity)
    for record in downloads:
        if (record_key(record.get("server_id"), record.get("entry_id")) == composite and
                file_exists(record.get("path", ""))):
            return record["path"]
    filename = safe_filename(item.get("title", "book"), extension, composite)
    path = BOOK_DIR + "/" + filename
    temporary = path + ".part"
    remove_if_present(temporary)
    try:
        size = stream_download(item["url"], temporary, server, "*/*", BOOK_LIMIT, True,
                               "Downloading " + item.get("title", "book"))
        remove_if_present(path)
        solaros.storage.rename(temporary, path)
    except Exception:
        remove_if_present(temporary)
        raise
    wanted = record_key(server["id"], item.get("id"))
    downloads[:] = [record for record in downloads
                    if record_key(record.get("server_id"), record.get("entry_id")) != wanted]
    downloads.insert(0, {"server_id": server["id"], "entry_id": item.get("id", ""),
                         "title": item.get("title", "Untitled"), "author": item.get("author", ""),
                         "path": path, "bytes": size})
    save_records(DOWNLOADS_PATH, downloads)
    return path


def server_name(servers, server_id):
    for server in servers:
        if server.get("id") == server_id:
            return server.get("name", "OPDS server")
    return "Missing server"


def draw_list(title, items, selected, footer, note=""):
    rows, cols = tui.size()
    tui.clear()
    heading = " " + title + " "
    if note:
        heading += "| " + note + " "
    tui.addstr(0, 0, clip(heading, cols), tui.INVERSE)
    visible = max(1, (rows - 2) // 2)
    start = (selected // visible) * visible
    row = 1
    for index in range(start, min(len(items), start + visible)):
        item = items[index]
        prefix = "> " if index == selected else "  "
        attr = tui.INVERSE if index == selected else 0
        marker = item.get("marker", "")
        tui.addstr(row, 0, clip(prefix + marker + item.get("title", "Untitled"), cols), attr)
        subtitle = item.get("subtitle", "")
        if subtitle:
            tui.addstr(row + 1, 4, clip(subtitle, max(0, cols - 4)))
        row += 2
    if not items:
        tui.addstr(3, 2, "No items")
    tui.addstr(rows - 1, 0, clip(footer, cols), tui.INVERSE)
    tui.refresh()


def list_loop(title, items, footer, extra_keys=(), idle_action=None):
    global _pending_key
    selected = 0
    idle_ticks = 0
    idle_done = idle_action is None
    draw_list(title, items, selected, footer)
    while not solaros.should_exit():
        if _pending_key is not None:
            key = _pending_key
            _pending_key = None
        else:
            key = tui.getch(250)
        if key is None:
            if not idle_done:
                idle_ticks += 1
                if idle_ticks >= 4:
                    idle_done = True
                    try:
                        idle_action()
                    except Exception:
                        pass
                    gc.collect()
                    draw_list(title, items, selected, footer)
            continue
        idle_ticks = 0
        if key == tui.KEY_ESCAPE or key == ord("q"):
            return None, key
        if key == tui.KEY_DOWN and items:
            selected = min(len(items) - 1, selected + 1)
            draw_list(title, items, selected, footer)
        elif key == tui.KEY_UP and items:
            selected = max(0, selected - 1)
            draw_list(title, items, selected, footer)
        elif key == tui.KEY_PAGE_DOWN and items:
            selected = min(len(items) - 1, selected + max(1, (tui.size()[0] - 2) // 2))
            draw_list(title, items, selected, footer)
        elif key == tui.KEY_PAGE_UP and items:
            selected = max(0, selected - max(1, (tui.size()[0] - 2) // 2))
            draw_list(title, items, selected, footer)
        elif key in extra_keys:
            return (selected if items else None), key
        elif (key == KEY_ENTER or key == KEY_RETURN) and items:
            return selected, key
    return None, tui.KEY_ESCAPE


def detail_loop(server, item, to_read, downloads):
    while not solaros.should_exit():
        starred = is_starred(to_read, server["id"], item)
        body = item.get("title", "Untitled")
        if item.get("author"):
            body += "\n\n" + item["author"]
        if item.get("summary"):
            body += "\n\n" + item["summary"]
        message("Book details", body,
                "Enter download  s {}  q back".format("unstar" if starred else "star"))
        key = wait_key()
        if key == tui.KEY_ESCAPE or key == ord("q"):
            return
        if key == ord("s"):
            toggle_star(to_read, server, item)
        elif key == KEY_ENTER or key == KEY_RETURN:
            message("Downloading", item.get("title", "book"), "Please wait")
            try:
                path = download_book(server, item, downloads)
                message("Downloaded", path, "Press any key")
            except Exception as error:
                message("Download failed", str(error), "Press any key")
            wait_key()


def browse_server(server, start_url, to_read, downloads):
    history = []
    url = start_url
    search_descriptor = ""
    while url and not solaros.should_exit():
        message("Connecting", server.get("name", "OPDS server"), "Please wait")
        try:
            feed = fetch_feed(server, url)
        except Exception as error:
            message("Catalog error", str(error), "Press any key")
            wait_key()
            return
        if feed.get("search"):
            search_descriptor = feed["search"]
        display = []
        for item in feed["items"]:
            copy = dict(item)
            if item.get("kind") == "book":
                copy["marker"] = "* " if is_starred(to_read, server["id"], item) else "  "
                copy["subtitle"] = item.get("author") or item.get("extension", "").upper()
            else:
                copy["marker"] = "> "
                copy["subtitle"] = "Browse"
            display.append(copy)
        if feed.get("next"):
            display.append({"kind": "next", "title": "Next page", "marker": "> ",
                            "subtitle": "More results", "url": feed["next"]})
        footer = "Enter open  s star  / search  q back"
        next_url = feed.get("next")
        idle_action = None
        if next_url:
            def cache_next_page(server=server, next_url=next_url):
                prefetched = fetch_feed(server, next_url, False)
                prefetched = None
            idle_action = cache_next_page
        selected, key = list_loop(feed["title"], display, footer,
                                  (ord("s"), ord("/")), idle_action)
        if key == ord("/"):
            if not search_descriptor:
                message("Search unavailable", "This server did not advertise OpenSearch.")
                wait_key()
                continue
            query = edit_text("Search " + server["name"], "Search terms", max_length=128)
            if query:
                try:
                    template = fetch_search_template(server, search_descriptor)
                    history.append(url)
                    url = template.replace("{searchTerms}", percent_encode(query))
                except Exception as error:
                    message("Search failed", str(error))
                    wait_key()
            continue
        if selected is None:
            if history:
                url = history.pop()
                continue
            return
        item = display[selected]
        if item.get("kind") == "book":
            if key == ord("s"):
                toggle_star(to_read, server, item)
            else:
                detail_loop(server, item, to_read, downloads)
        elif key != ord("s"):
            history.append(url)
            url = item.get("url")


def add_server(servers):
    name = edit_text("Add server", "Name", max_length=64)
    if not name:
        return
    url = edit_text("Add server", "OPDS or Kavita base URL", max_length=512)
    if not url:
        return
    if not (url.startswith("http://") or url.startswith("https://")):
        message("Invalid address", "Server URL must start with http:// or https://")
        wait_key()
        return
    key = edit_text("Add server", "Kavita auth key (optional)", max_length=128, secret=True)
    if key is None:
        return
    username = ""
    password = ""
    if not key:
        username = edit_text("Add server", "Basic username (optional)", max_length=128)
        if username is None:
            return
        if username:
            password = edit_text("Add server", "Basic password", max_length=128, secret=True)
            if password is None:
                return
    server = {"id": stable_id(url + "\n" + name), "name": name, "url": url.rstrip("/"),
              "key": key, "username": username, "password": password}
    message("Testing server", name, "Please wait")
    try:
        feed = fetch_feed(server, server_catalog_url(server))
        server["name"] = name or feed.get("title") or "OPDS server"
    except Exception as error:
        message("Connection failed", str(error), "Press any key")
        wait_key()
        return
    servers.append(server)
    save_json(SERVERS_PATH, {"servers": servers})


def manage_servers(servers):
    while not solaros.should_exit():
        display = [{"title": server["name"], "subtitle": origin(server_catalog_url(server))}
                   for server in servers]
        selected, key = list_loop("Manage servers", display,
                                  "a add  x remove  Enter test  q back", (ord("a"), ord("x")))
        if key == ord("a"):
            add_server(servers)
            continue
        if selected is None:
            return
        server = servers[selected]
        if key == ord("x"):
            message("Remove server?", server["name"], "x confirm  any key cancel")
            if wait_key() == ord("x"):
                del servers[selected]
                save_json(SERVERS_PATH, {"servers": servers})
        else:
            message("Testing server", server["name"], "Please wait")
            try:
                feed = fetch_feed(server, server_catalog_url(server))
                message("Connection works", feed.get("title", server["name"]))
            except Exception as error:
                message("Connection failed", str(error))
            wait_key()


def to_read_loop(servers, to_read, downloads):
    while not solaros.should_exit():
        display = []
        for record in to_read:
            copy = dict(record)
            copy["marker"] = "* "
            copy["subtitle"] = server_name(servers, record.get("server_id"))
            display.append(copy)
        selected, key = list_loop("To Read", display, "Enter details  s remove  q back", (ord("s"),))
        if selected is None:
            return
        record = to_read[selected]
        if key == ord("s"):
            del to_read[selected]
            save_records(READING_PATH, to_read)
            continue
        server = None
        for candidate in servers:
            if candidate.get("id") == record.get("server_id"):
                server = candidate
                break
        if not server:
            message("Server missing", "The saved book metadata is available, but its server profile was removed.")
            wait_key()
            continue
        item = {"kind": "book", "id": record.get("entry_id", ""),
                "title": record.get("title", "Untitled"), "author": record.get("author", ""),
                "summary": record.get("summary", ""), "url": record.get("url", ""),
                "extension": record.get("extension", ""), "media_type": record.get("media_type", "")}
        detail_loop(server, item, to_read, downloads)


def downloads_loop(servers, downloads):
    display = []
    for record in downloads:
        display.append({"title": record.get("title", "Untitled"),
                        "subtitle": server_name(servers, record.get("server_id")) + " · " + record.get("path", "")})
    selected, unused = list_loop("Downloaded", display, "Enter location  q back")
    if selected is not None:
        message("Downloaded book", downloads[selected].get("path", "Unknown path"), "Press any key")
        wait_key()


def main():
    ensure_dir(APP_DIR)
    ensure_dir(BOOK_DIR)
    servers = load_servers()
    to_read = load_records(READING_PATH)
    downloads = load_records(DOWNLOADS_PATH)
    try:
        while not solaros.should_exit():
            home = [
                {"kind": "to-read", "title": "To Read", "subtitle": "{} saved books".format(len(to_read))},
                {"kind": "downloaded", "title": "Downloaded", "subtitle": "{} local books".format(len(downloads))},
            ]
            for server in servers:
                home.append({"kind": "server", "title": server["name"],
                             "subtitle": origin(server_catalog_url(server)), "server": server})
            home.append({"kind": "manage", "title": "Manage Servers", "subtitle": "Add, remove, or test connections"})
            selected, unused = list_loop("Book Repositories", home, "Enter open  q quit")
            if selected is None:
                break
            item = home[selected]
            if item["kind"] == "to-read":
                to_read_loop(servers, to_read, downloads)
            elif item["kind"] == "downloaded":
                downloads_loop(servers, downloads)
            elif item["kind"] == "manage":
                manage_servers(servers)
            else:
                server = item["server"]
                browse_server(server, server_catalog_url(server), to_read, downloads)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        message("OPDS error", str(error), "Press any key")
        wait_key()
    finally:
        remove_if_present(TEMP_PATH)
        gc.collect()
        tui.clear()
        tui.refresh()


if __name__ == "__main__":
    main()

"""Text-first Wikipedia reader for SolarOS."""

import gc
import json
import sys

import solaros
from solaros import tui


def app_directory():
    path = sys.argv[0] if sys.argv else "wikipedia.py"
    if not path or "/" not in path:
        try:
            path = __file__
        except NameError:
            path = "wikipedia.py"
    separator = path.rfind("/")
    if separator < 0:
        return "."
    return path[:separator] if separator > 0 else "/"


APP_DIR = app_directory()
CACHE_DIR = APP_DIR + "/cache"
CONFIG_PATH = APP_DIR + "/config.json"
INDEX_PATH = APP_DIR + "/articles.json"
BOOKMARKS_PATH = APP_DIR + "/bookmarks.json"
HISTORY_PATH = APP_DIR + "/history.json"
OFFLINE_PATH = APP_DIR + "/offline.json"
HTML_LIMIT = 4 * 1024 * 1024
SEARCH_LIMIT = 128 * 1024
MAX_ARTICLES = 20
USER_AGENT = "SolarOS-Wikipedia-Reader/0.1"
KEY_ENTER = 10
KEY_RETURN = 13
KEY_BACKSPACE = 8
KEY_DELETE_CHAR = 127


def clean_space(value):
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def clip(value, width):
    value = clean_space(value)
    return value if len(value) <= width else value[:max(0, width - 1)] + "~"


def wrap(value, width):
    lines = []
    text = clean_space(value)
    while text:
        if len(text) <= width:
            lines.append(text)
            break
        cut = text.rfind(" ", 0, width + 1)
        if cut < 1:
            cut = width
        lines.append(text[:cut])
        text = text[cut:].lstrip()
    return lines


def message(title, body, footer="Press any key"):
    rows, cols = tui.size()
    tui.clear()
    tui.addstr(0, 0, clip(" " + title + " ", cols), tui.INVERSE)
    row = 2
    for paragraph in str(body or "").split("\n"):
        for line in wrap(paragraph, cols - 2) or [""]:
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


def edit_text(title, label, initial="", max_length=160):
    value = initial
    while not solaros.should_exit():
        message(title, label + "\n\n" + value + "_", "Enter accept  Esc cancel")
        key = tui.getch(250)
        if key is None:
            continue
        if key == tui.KEY_ESCAPE:
            return None
        if key in (KEY_ENTER, KEY_RETURN):
            return value.strip()
        if key in (KEY_BACKSPACE, KEY_DELETE_CHAR, tui.KEY_DELETE):
            value = value[:-1]
        elif isinstance(key, int) and 32 <= key <= 126 and len(value) < max_length:
            value += chr(key)
    return None


def ensure_dir(path):
    try:
        solaros.storage.mkdir(path)
    except OSError:
        pass


def remove(path):
    try:
        solaros.storage.remove(path)
    except OSError:
        pass


def exists(path):
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


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
    remove(path)
    solaros.storage.rename(temporary, path)
    gc.collect()


def stable_id(value):
    first = 0x1357
    second = 0x2468
    for character in str(value or ""):
        code = ord(character)
        first = ((first * 33) + code) & 0xffff
        second = ((second * 131) ^ code) & 0xffff
    return "{:04x}{:04x}".format(first, second)


def percent_encode(value):
    result = []
    for byte in str(value or "").encode("utf-8"):
        if ((48 <= byte <= 57) or (65 <= byte <= 90) or
                (97 <= byte <= 122) or byte in (45, 46, 95, 126)):
            result.append(chr(byte))
        else:
            result.append("%{:02X}".format(byte))
    return "".join(result)


def decode_entities(text):
    if "&" not in text:
        return text
    named = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'",
             "nbsp": " ", "ndash": "-", "mdash": "--", "hellip": "..."}
    for name, value in named.items():
        text = text.replace("&" + name + ";", value)
    if "&#" not in text:
        return text
    result = []
    position = 0
    while position < len(text):
        if text[position] != "&":
            result.append(text[position])
            position += 1
            continue
        end = text.find(";", position + 1, position + 16)
        if end < 0:
            result.append("&")
            position += 1
            continue
        name = text[position + 1:end]
        value = None
        if name.startswith("#"):
            try:
                value = chr(int(name[2:], 16) if name.startswith("#x") else int(name[1:]))
            except Exception:
                value = None
        result.append(value if value is not None else text[position:end + 1])
        position = end + 1
    return "".join(result)


def strip_tags(text):
    output = []
    inside = False
    for character in str(text or ""):
        if character == "<":
            inside = True
        elif character == ">":
            inside = False
        elif not inside:
            output.append(character)
    return clean_space(decode_entities("".join(output)))


def config():
    value = load_json(CONFIG_PATH, {"language": "en"})
    language = clean_space(value.get("language", "en")).lower()
    if not language or any(not ("a" <= char <= "z" or char == "-") for char in language):
        language = "en"
    return {"language": language}


def api_base(settings):
    return "https://{}.wikipedia.org".format(settings["language"])


def headers(accept="application/json"):
    return {"Accept": accept, "User-Agent": USER_AGENT, "Api-User-Agent": USER_AGENT}


def request_json(url):
    response = solaros.http.get(url, headers(), 30000, SEARCH_LIMIT, True)
    status = response.get("status_code", 0)
    if status < 200 or status >= 300:
        raise RuntimeError("HTTP {}".format(status))
    body = response.get("body", b"")
    if response.get("truncated"):
        raise RuntimeError("response too large")
    value = json.loads(body.decode("utf-8"))
    body = None
    response = None
    gc.collect()
    return value


def request_text(url):
    response = solaros.http.get(url, headers(), 30000, SEARCH_LIMIT, True)
    status = response.get("status_code", 0)
    if status < 200 or status >= 300:
        raise RuntimeError("HTTP {}".format(status))
    if response.get("truncated"):
        raise RuntimeError("response too large")
    return response.get("body", b"").decode("utf-8")


def json_string_field(text, name):
    marker = '"' + name + '"'
    position = text.find(marker)
    if position < 0:
        return ""
    position = text.find(":", position + len(marker))
    if position < 0:
        return ""
    position += 1
    while position < len(text) and text[position] in " \r\n\t":
        position += 1
    if position >= len(text) or text[position] != '"':
        return ""
    position += 1
    result = []
    while position < len(text):
        character = text[position]
        position += 1
        if character == '"':
            return "".join(result)
        if character != "\\":
            result.append(character)
            continue
        if position >= len(text):
            break
        escaped = text[position]
        position += 1
        replacements = {'"': '"', "\\": "\\", "/": "/", "b": "\b",
                        "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
        if escaped == "u" and position + 4 <= len(text):
            try:
                result.append(chr(int(text[position:position + 4], 16)))
                position += 4
            except Exception:
                pass
        else:
            result.append(replacements.get(escaped, escaped))
    return ""


def draw_progress(received, total):
    if total > 0:
        percent = min(100, received * 100 // total)
        filled = percent * 20 // 100
        body = "[" + "#" * filled + "-" * (20 - filled) + "]\n\n"
        body += "{}%  {} / {} KB".format(percent, received // 1024,
                                          (total + 1023) // 1024)
    else:
        body = "{} KB received".format(received // 1024)
    message("Downloading article", body, "Please wait")


def stream_article(url, path):
    handle = solaros.http.stream_open("GET", url, None, headers("application/xml"), 30000, True)
    status = 0
    total = -1
    received = 0
    next_update = 0
    try:
        with open(path, "wb") as output:
            while not solaros.should_exit():
                event = solaros.http.stream_read(handle, 1000)
                if event is None:
                    continue
                kind = event.get("type")
                if kind == "response":
                    status = event.get("status_code", 0)
                    total = event.get("content_length", -1)
                    if status < 200 or status >= 300:
                        raise RuntimeError("HTTP {}".format(status))
                    draw_progress(0, total)
                elif kind == "data":
                    chunk = event.get("data", b"")
                    received += len(chunk)
                    if received > HTML_LIMIT:
                        raise RuntimeError("article exceeds 4 MB limit")
                    output.write(chunk)
                    if received >= next_update:
                        draw_progress(received, total)
                        next_update = received + max(8192, total // 20 if total > 0 else 0)
                elif kind == "error":
                    raise RuntimeError(event.get("error_name", "HTTP error"))
                elif kind == "complete":
                    draw_progress(received, total if total > 0 else received)
                    break
            output.flush()
    finally:
        solaros.http.stream_close(handle)
        gc.collect()
    if status < 200 or status >= 300:
        raise RuntimeError("HTTP {}".format(status or "request failed"))


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
    position = after_at
    while position < len(tag) and tag[position].isspace():
        position += 1
    if position >= len(tag) or tag[position] != "=":
        return ""
    position += 1
    while position < len(tag) and tag[position].isspace():
        position += 1
    if position >= len(tag):
        return ""
    quote = tag[position]
    if quote in ("'", '"'):
        end = tag.find(quote, position + 1)
        return tag[position + 1:end if end >= 0 else len(tag)]
    end = position
    while end < len(tag) and tag[end] not in " >":
        end += 1
    return tag[position:end]


def write_wrapped(output, text, width):
    text = decode_entities(text)
    for paragraph in text.replace("\r", "").split("\n"):
        paragraph = clean_space(paragraph)
        if paragraph.startswith("==") and paragraph.endswith("=="):
            paragraph = "## " + paragraph.strip("= ")
        if paragraph:
            for line in wrap(paragraph, width):
                output.write(line + "\n")
        output.write("\n")


def parse_extract_xml(source_path, body_path, width):
    started = False
    pending = ""
    with open(body_path, "w") as output, open(source_path, "r") as source:
        while True:
            chunk = source.read(8192)
            if not chunk:
                break
            pending += chunk
            if not started:
                marker = pending.find("<extract")
                if marker < 0:
                    pending = pending[-16:]
                    continue
                opening = pending.find(">", marker)
                if opening < 0:
                    pending = pending[marker:]
                    continue
                pending = pending[opening + 1:]
                started = True
            closing = pending.find("</extract>")
            if closing >= 0:
                write_wrapped(output, pending[:closing], width)
                return
            safe = pending.rfind("\n")
            if safe >= 0:
                write_wrapped(output, pending[:safe + 1], width)
                pending = pending[safe + 1:]
        if started and pending:
            write_wrapped(output, pending, width)


def parse_links_xml(source_path, links_path):
    buffer = ""
    seen = set()
    count = 0
    with open(links_path, "w") as output, open(source_path, "r") as source:
        while count < 200:
            chunk = source.read(8192)
            if not chunk:
                break
            buffer += chunk
            position = 0
            while count < 200:
                start = buffer.find("<pl ", position)
                if start < 0:
                    buffer = buffer[max(0, len(buffer) - 32):]
                    break
                end = buffer.find("/>", start + 4)
                if end < 0:
                    buffer = buffer[start:]
                    break
                title = decode_entities(attribute(buffer[start:end + 2], "title"))
                if title and ":" not in title and title not in seen:
                    seen.add(title)
                    count += 1
                    output.write(json.dumps({"id": count,
                                             "key": percent_encode(title.replace(" ", "_")),
                                             "title": title}) + "\n")
                position = end + 2


def article_paths(key, language):
    directory = CACHE_DIR + "/v4-" + stable_id(language + "\n" + key)
    return directory, directory + "/body.txt", directory + "/links.jsonl"


def offline_items():
    return load_json(OFFLINE_PATH, {"items": []}).get("items", [])


def same_article(item, key, language):
    return (item.get("key") == key and
            item.get("language", language) == language)


def tag_legacy_records(language):
    for path in (INDEX_PATH, HISTORY_PATH, BOOKMARKS_PATH, OFFLINE_PATH):
        data = load_json(path, {"items": []})
        items = data.get("items", []) if isinstance(data, dict) else []
        changed = False
        for item in items:
            if isinstance(item, dict) and not item.get("language"):
                item["language"] = language
                changed = True
        if changed:
            save_json(path, {"items": items})


def is_offline(key, language):
    return any(same_article(item, key, language) for item in offline_items())


def remove_article_files(key, language):
    directories = [CACHE_DIR + "/v4-" + stable_id(language + "\n" + key)]
    directories.extend(CACHE_DIR + "/" + version + stable_id(key)
                       for version in ("v2-", "v3-"))
    for directory in directories:
        remove(directory + "/body.txt")
        remove(directory + "/links.jsonl")
        remove(directory + "/source.html")
        remove(directory + "/source.xml")
        try:
            solaros.storage.rmdir(directory)
        except OSError:
            pass


def touch_article(key, title, language):
    records = load_json(INDEX_PATH, {"items": []}).get("items", [])
    records = [item for item in records if not same_article(item, key, language)]
    if not is_offline(key, language):
        records.insert(0, {"key": key, "title": title, "language": language})
    evicted = records[MAX_ARTICLES:]
    save_json(INDEX_PATH, {"items": records[:MAX_ARTICLES]})
    for item in evicted:
        item_language = item.get("language", language)
        if not is_offline(item.get("key"), item_language):
            remove_article_files(item.get("key"), item_language)
    history = load_json(HISTORY_PATH, {"items": []}).get("items", [])
    history = [item for item in history if not same_article(item, key, language)]
    history.insert(0, {"key": key, "title": title, "language": language})
    save_json(HISTORY_PATH, {"items": history[:30]})


def prepare_article(settings, key, title, language=None):
    language = language or settings["language"]
    directory, body_path, links_path = article_paths(key, language)
    for version in ("v3-", "v2-"):
        legacy = CACHE_DIR + "/" + version + stable_id(key)
        if not exists(body_path) and exists(legacy + "/body.txt"):
            ensure_dir(directory)
            for filename in ("body.txt", "links.jsonl"):
                try:
                    solaros.storage.rename(legacy + "/" + filename,
                                           directory + "/" + filename)
                except OSError:
                    pass
            try:
                solaros.storage.rmdir(legacy)
            except OSError:
                pass
    if exists(body_path) and exists(links_path):
        touch_article(key, title, language)
        return body_path, links_path
    ensure_dir(CACHE_DIR)
    ensure_dir(directory)
    source_path = directory + "/source.xml"
    remove(source_path)
    article_settings = {"language": language}
    url = (api_base(article_settings) + "/w/api.php?action=query&prop=extracts%7Clinks"
           "&explaintext=1&exsectionformat=plain&plnamespace=0&pllimit=200"
           "&redirects=1&titles=" + key + "&format=xml")
    stream_article(url, source_path)
    message("Processing article", "Preparing plain text and article links", "Please wait")
    try:
        parse_extract_xml(source_path, body_path, max(20, tui.size()[1] - 2))
        parse_links_xml(source_path, links_path)
    finally:
        remove(source_path)
        gc.collect()
    touch_article(key, title, language)
    return body_path, links_path


def list_loop(title, items, footer="Enter open  q back"):
    selected = 0
    dirty = True
    while not solaros.should_exit():
        if dirty:
            rows, cols = tui.size()
            tui.clear()
            tui.addstr(0, 0, clip(" " + title + " ", cols), tui.INVERSE)
            visible = max(1, (rows - 2) // 2)
            start = selected // visible * visible
            row = 1
            for index in range(start, min(len(items), start + visible)):
                item = items[index]
                attr = tui.INVERSE if index == selected else 0
                prefix = "> " if index == selected else "  "
                tui.addstr(row, 0, clip(prefix + item.get("title", "Untitled"), cols), attr)
                subtitle = item.get("subtitle", "")
                if subtitle:
                    tui.addstr(row + 1, 4, clip(subtitle, cols - 4))
                row += 2
            if not items:
                tui.addstr(3, 2, "No items")
            tui.addstr(rows - 1, 0, clip(footer, cols), tui.INVERSE)
            tui.refresh()
            dirty = False
        key = tui.getch(250)
        if key is None:
            continue
        if key in (tui.KEY_ESCAPE, ord("q")):
            return None
        if key == tui.KEY_DOWN and items:
            selected = min(len(items) - 1, selected + 1)
            dirty = True
        elif key == tui.KEY_UP and items:
            selected = max(0, selected - 1)
            dirty = True
        elif key == tui.KEY_PAGE_DOWN and items:
            selected = min(len(items) - 1, selected + visible)
            dirty = True
        elif key == tui.KEY_PAGE_UP and items:
            selected = max(0, selected - visible)
            dirty = True
        elif key in (KEY_ENTER, KEY_RETURN) and items:
            return items[selected]
    return None


def search(settings):
    query = edit_text("Search Wikipedia", "Article title or subject")
    if not query:
        return None
    message("Searching Wikipedia", query, "Please wait")
    url = api_base(settings) + "/w/rest.php/v1/search/page?q=" + percent_encode(query) + "&limit=12"
    data = request_json(url)
    results = []
    for page in data.get("pages", []):
        key = percent_encode(page.get("key") or page.get("title", ""))
        results.append({"key": key, "title": page.get("title", "Untitled"),
                        "subtitle": strip_tags(page.get("description") or page.get("excerpt", ""))})
    return list_loop("Search results", results)


def random_article(settings):
    message("Random article", "Letting Wikipedia choose...", "Please wait")
    url = (api_base(settings) + "/w/api.php?action=query&generator=random&grnnamespace=0"
           "&grnlimit=1&prop=info&format=json&formatversion=2")
    text = request_text(url)
    title = json_string_field(text, "title")
    if not title:
        raise RuntimeError("Wikipedia returned no article")
    return {"title": title, "key": percent_encode(title.replace(" ", "_"))}


def load_article_links(path):
    found = []
    with open(path, "r") as source:
        for line in source:
            try:
                item = json.loads(line)
                item["subtitle"] = "Wikipedia article"
                found.append(item)
            except Exception:
                pass
    found.sort(key=lambda item: item.get("title", "").lower())
    return found


def is_bookmarked(key, language):
    items = load_json(BOOKMARKS_PATH, {"items": []}).get("items", [])
    return any(same_article(item, key, language) for item in items)


def toggle_bookmark(key, title, language):
    items = load_json(BOOKMARKS_PATH, {"items": []}).get("items", [])
    for index, item in enumerate(items):
        if same_article(item, key, language):
            del items[index]
            save_json(BOOKMARKS_PATH, {"items": items})
            return False
    items.insert(0, {"key": key, "title": title, "language": language})
    save_json(BOOKMARKS_PATH, {"items": items})
    return True


def toggle_offline(key, title, language):
    items = offline_items()
    for index, item in enumerate(items):
        if same_article(item, key, language):
            del items[index]
            save_json(OFFLINE_PATH, {"items": items})
            touch_article(key, title, language)
            return False
    items.insert(0, {"key": key, "title": title, "language": language})
    save_json(OFFLINE_PATH, {"items": items})
    cached = load_json(INDEX_PATH, {"items": []}).get("items", [])
    cached = [item for item in cached if not same_article(item, key, language)]
    save_json(INDEX_PATH, {"items": cached})
    return True


def read_article(settings, article, start_offset=0):
    key = article["key"]
    title = article["title"]
    language = article.get("language", settings["language"])
    body_path, links_path = prepare_article(settings, key, title, language)
    offsets = [start_offset]
    page = 0
    dirty = True
    lines = []
    next_offset = -1
    while not solaros.should_exit():
        if dirty:
            rows, cols = tui.size()
            lines = []
            with open(body_path, "r") as source:
                source.seek(offsets[page])
                for unused in range(rows - 2):
                    line = source.readline()
                    if not line:
                        break
                    lines.append(line.rstrip("\n"))
                next_offset = source.tell()
                if not source.read(1):
                    next_offset = -1
            tui.clear()
            tui.addstr(0, 0, clip(" " + title + " ", cols), tui.INVERSE)
            for row, line in enumerate(lines, 1):
                tui.addstr(row, 1, clip(line, cols - 2))
            star = "unstar" if is_bookmarked(key, language) else "star"
            keep = "unkeep" if is_offline(key, language) else "offline"
            tui.addstr(rows - 1, 0,
                       clip("PgUp/Dn l links s {} o {} q back".format(star, keep), cols),
                       tui.INVERSE)
            tui.refresh()
            dirty = False
        keypress = tui.getch(250)
        if keypress is None:
            continue
        if keypress in (tui.KEY_ESCAPE, ord("q")):
            return None, offsets[page]
        if keypress in (tui.KEY_PAGE_DOWN, tui.KEY_DOWN) and next_offset >= 0:
            if page + 1 == len(offsets):
                offsets.append(next_offset)
            page += 1
            dirty = True
        elif keypress in (tui.KEY_PAGE_UP, tui.KEY_UP) and page > 0:
            page -= 1
            dirty = True
        elif keypress == ord("s"):
            toggle_bookmark(key, title, language)
            dirty = True
        elif keypress == ord("o"):
            toggle_offline(key, title, language)
            dirty = True
        elif keypress in (ord("l"), KEY_ENTER, KEY_RETURN):
            choices = load_article_links(links_path)
            if choices:
                selected = list_loop("Article links", choices)
                if selected:
                    return {"key": selected["key"], "title": selected["title"],
                            "language": language}, offsets[page]
            else:
                message("No links", "This article has no linked Wikipedia pages.")
                wait_key()


def article_session(settings, article):
    stack = [{"article": article, "offset": 0}]
    while stack and not solaros.should_exit():
        current = stack[-1]
        try:
            linked, offset = read_article(settings, current["article"], current["offset"])
            current["offset"] = offset
            if linked:
                stack.append({"article": linked, "offset": 0})
            else:
                stack.pop()
        except Exception as error:
            message("Wikipedia error", str(error), "Press any key")
            wait_key()
            stack.pop()


def saved_list(path, title):
    items = load_json(path, {"items": []}).get("items", [])
    for item in items:
        item["subtitle"] = item.get("key", "").replace("_", " ")
    return list_loop(title, items)


def confirm(title, body):
    choice = list_loop(title, [
        {"title": "No", "value": False, "subtitle": "Keep everything"},
        {"title": "Yes", "value": True, "subtitle": body},
    ], "Enter choose  q cancel")
    return bool(choice and choice.get("value"))


def clear_cache(default_language):
    records = load_json(INDEX_PATH, {"items": []}).get("items", [])
    for item in records:
        language = item.get("language", default_language)
        if not is_offline(item.get("key"), language):
            remove_article_files(item.get("key"), language)
    save_json(INDEX_PATH, {"items": []})


def settings_loop(settings):
    while not solaros.should_exit():
        choice = list_loop("Wikipedia settings", [
            {"kind": "language", "title": "Language: " + settings["language"],
             "subtitle": "Wikipedia edition"},
            {"kind": "cache", "title": "Clear article cache",
             "subtitle": "Offline-kept articles are preserved"},
            {"kind": "history", "title": "Clear recent history",
             "subtitle": "Cached and offline articles are preserved"},
        ])
        if not choice:
            return settings
        if choice["kind"] == "language":
            language = edit_text("Wikipedia language", "Language code", settings["language"], 12)
            if language:
                settings = {"language": language.lower()}
                save_json(CONFIG_PATH, settings)
        elif choice["kind"] == "cache":
            if confirm("Clear cache?", "Remove disposable article files"):
                clear_cache(settings["language"])
                message("Cache cleared", "Offline library articles were preserved.")
                wait_key()
        elif choice["kind"] == "history":
            if confirm("Clear history?", "Remove recently viewed entries"):
                save_json(HISTORY_PATH, {"items": []})
                message("History cleared", "Cached articles and offline library were preserved.")
                wait_key()


def main():
    ensure_dir(APP_DIR)
    ensure_dir(CACHE_DIR)
    settings = config()
    tag_legacy_records(settings["language"])
    try:
        while not solaros.should_exit():
            home = [
                {"kind": "search", "title": "Search Wikipedia", "subtitle": "Titles and article text"},
                {"kind": "random", "title": "Random article", "subtitle": "Surprise me"},
                {"kind": "recent", "title": "Recently read", "subtitle": "Your reading history"},
                {"kind": "offline", "title": "Offline library", "subtitle": "Articles kept on this device"},
                {"kind": "bookmarks", "title": "Bookmarks", "subtitle": "Saved articles"},
                {"kind": "settings", "title": "Settings", "subtitle": "Language and storage"},
            ]
            choice = list_loop("Wikipedia", home, "Enter open  q quit")
            if not choice:
                break
            try:
                article = None
                if choice["kind"] == "search":
                    article = search(settings)
                elif choice["kind"] == "random":
                    article = random_article(settings)
                elif choice["kind"] == "recent":
                    article = saved_list(HISTORY_PATH, "Recently read")
                elif choice["kind"] == "offline":
                    article = saved_list(OFFLINE_PATH, "Offline library")
                elif choice["kind"] == "bookmarks":
                    article = saved_list(BOOKMARKS_PATH, "Bookmarks")
                elif choice["kind"] == "settings":
                    settings = settings_loop(settings)
                if article:
                    article_session(settings, article)
            except Exception as error:
                message("Wikipedia error", str(error), "Press any key")
                wait_key()
    except KeyboardInterrupt:
        pass
    finally:
        tui.clear()
        tui.refresh()


if __name__ == "__main__":
    main()

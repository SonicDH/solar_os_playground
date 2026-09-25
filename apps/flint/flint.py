"""Flint: an offline Markdown vault and daily-notes app for SolarOS."""

import gc
import binascii
import hashlib
import io
import json
import sys

import solaros
from solaros import gfx

from flint_core import (MAX_BLOCK, MAX_NOTE_BYTES, MAX_NOTES, MAX_PATH,
                        all_digits, all_tags, backlinks, basename, clean_document,
                        clean_line, dirname, inside, is_note_path, join_blocks,
                        link_items, metadata, normalize_index, normalize_path,
                        notes_for_tag, remove_from_index, rename_links,
                        rename_title_heading,
                        resolve_link, resolve_links, safe_filename, search_index, split_blocks,
                        stem, strip_inline, title_key, touch_recent, upsert, utf8_size)


def app_directory():
    path = sys.argv[0] if sys.argv else "flint.py"
    if not path or "/" not in path:
        try:
            path = __file__
        except NameError:
            path = "flint.py"
    position = path.rfind("/")
    return path[:position] if position > 0 else "/" if position == 0 else "."


APP_DIR = app_directory()
DATA_DIR = "/.flint"
CONFIG_PATH = DATA_DIR + "/config.json"
INDEX_PATH = DATA_DIR + "/index.json"
DEFAULT_ROOT = "/notes/vault"
DEFAULT_DAILY_FOLDER = "Daily"
KEY_ENTER = 13
KEY_LF = 10
KEY_BACKSPACE = 8
KEY_DELETE = 127
KEY_CTRL_B = 2
KEY_CTRL_S = 19
HEADER_H = 43
FOOTER_H = 25
ROW_H = 43
MIN_WIDTH = 200
MIN_HEIGHT = 140
REFRESH_ERRORS = []


def clip(value, count):
    value = clean_line(value, 1000)
    if len(value) <= count:
        return value
    return value[:max(0, count - 1)] + ("~" if count else "")


def raw_clip(value, count):
    """Clip preformatted text without collapsing meaningful indentation."""
    value = str(value).replace("\t", "    ").replace("\r", "")
    value = "".join(character if character >= " " else " " for character in value)
    if len(value) <= count:
        return value
    return value[:max(0, count - 1)] + ("~" if count else "")


def wait_key():
    while not solaros.should_exit():
        key = gfx.getch(250)
        if key is not None:
            return key
    return gfx.KEY_ESCAPE


def text_key(key):
    """Accept printable Unicode without mistaking navigation keys for text."""
    specials = (gfx.KEY_ESCAPE, gfx.KEY_UP, gfx.KEY_DOWN, gfx.KEY_LEFT,
                gfx.KEY_RIGHT, getattr(gfx, "KEY_PAGE_UP", -1),
                getattr(gfx, "KEY_PAGE_DOWN", -1), getattr(gfx, "KEY_HOME", -1),
                getattr(gfx, "KEY_END", -1), getattr(gfx, "KEY_DELETE", -1))
    return (isinstance(key, int) and key not in specials and
            (32 <= key <= 126 or 160 <= key <= 0x10FFFF) and
            not (0xD800 <= key <= 0xDFFF))


def draw_header(width, title, subtitle="", right=""):
    gfx.color(gfx.BLACK)
    gfx.fill_rect(0, 0, width, HEADER_H)
    gfx.color(gfx.WHITE)
    gfx.font(gfx.FONT_BOLD_16)
    reserved = len(right) * 6 + 12 if right else 0
    gfx.text(9, 18, clip(title, max(1, (width - 18 - reserved) // 8)))
    if right:
        gfx.font(gfx.FONT_MONO_12)
        gfx.text(max(9, width - 8 - len(right) * 6), 18, right)
    if subtitle:
        gfx.font(gfx.FONT_MONO_12)
        gfx.text(9, 36, clip(subtitle, max(1, (width - 18) // 6)))


def draw_footer(width, height, text):
    y = height - FOOTER_H
    gfx.color(gfx.BLACK)
    gfx.fill_rect(0, y, width, FOOTER_H)
    gfx.color(gfx.WHITE)
    gfx.font(gfx.FONT_MONO_12)
    gfx.text(6, y + 17, clip(text, max(1, (width - 12) // 6)))


def wrap(text, columns, maximum=1400):
    columns = max(4, columns)
    lines = []
    for source in clean_document(text).split("\n"):
        words = source.split()
        current = ""
        if not words:
            lines.append("")
        for word in words:
            while len(word) > columns:
                if current:
                    lines.append(current)
                    current = ""
                lines.append(word[:columns])
                word = word[columns:]
            trial = word if not current else current + " " + word
            if len(trial) > columns:
                if current:
                    lines.append(current)
                current = word
            else:
                current = trial
            if len(lines) >= maximum:
                return lines[:maximum]
        if current:
            lines.append(current)
    return lines[:maximum]


def draw_message(width, height, title, body, footer="Press any key"):
    gfx.clear(gfx.WHITE)
    draw_header(width, title)
    gfx.color(gfx.BLACK)
    gfx.font(gfx.FONT_MONO_14)
    columns = max(8, (width - 24) // 7)
    visible = max(1, (height - HEADER_H - FOOTER_H - 8) // 19)
    y = HEADER_H + 20
    for line in wrap(body, columns, visible):
        gfx.text(12, y, line)
        y += 19
    draw_footer(width, height, footer)
    gfx.refresh()


def message(width, height, title, body):
    draw_message(width, height, title, body)
    wait_key()


def confirm(width, height, title, body):
    draw_message(width, height, title, body, "Y confirm   any other key cancels")
    return wait_key() in (ord("y"), ord("Y"))


def draw_choice_row(width, options, index, start, selected):
    row = index - start
    y = HEADER_H + row * 31
    gfx.color(gfx.BLACK if index == selected else gfx.WHITE)
    gfx.fill_rect(4, y + 2, width - 8, 28)
    gfx.color(gfx.WHITE if index == selected else gfx.BLACK)
    gfx.font(gfx.FONT_MONO_14)
    gfx.text(10, y + 21, clip(options[index], max(4, (width - 20) // 7)))


def choose(width, height, title, options, selected=0, subtitle="",
           footer="Enter choose   Esc back", hotkeys=(), selection_state=None):
    if not options:
        return None
    selected = max(0, min(selected, len(options) - 1))
    previous = None
    previous_start = None
    while not solaros.should_exit():
        counter = "{}/{}".format(selected + 1, len(options))
        visible = max(1, (height - HEADER_H - FOOTER_H) // 31)
        start = (selected // visible) * visible
        if previous_start != start:
            gfx.clear(gfx.WHITE)
            for index in range(start, min(len(options), start + visible)):
                draw_choice_row(width, options, index, start, selected)
            draw_footer(width, height, footer)
        else:
            if previous is not None and start <= previous < start + visible:
                draw_choice_row(width, options, previous, start, selected)
            draw_choice_row(width, options, selected, start, selected)
        draw_header(width, title, subtitle, counter)
        gfx.refresh()
        previous = selected
        previous_start = start
        key = wait_key()
        if key in hotkeys:
            if selection_state is not None:
                selection_state[0] = selected
            return -key - 1
        if key in (gfx.KEY_ESCAPE, ord("q"), ord("Q")):
            return None
        if key in (gfx.KEY_UP, ord("k")):
            selected = (selected - 1) % len(options)
        elif key in (gfx.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(options)
        elif key == getattr(gfx, "KEY_PAGE_UP", -1001):
            selected = max(0, selected - visible)
        elif key == getattr(gfx, "KEY_PAGE_DOWN", -1002):
            selected = min(len(options) - 1, selected + visible)
        elif key in (KEY_ENTER, KEY_LF, gfx.KEY_RIGHT):
            return selected
    return None


def edit_line(width, height, title, label, initial="", limit=100):
    value = clean_line(initial, limit)
    while not solaros.should_exit():
        gfx.clear(gfx.WHITE)
        draw_header(width, title, clip(label, 30), "{}/{}".format(len(value), limit))
        gfx.color(gfx.BLACK)
        gfx.font(gfx.FONT_MONO_16)
        columns = max(8, (width - 24) // 8)
        shown = value + "_"
        lines = [shown[index:index + columns] for index in range(0, len(shown), columns)] or ["_"]
        visible = max(1, (height - HEADER_H - FOOTER_H - 8) // 23)
        y = HEADER_H + 29
        for line in lines[-visible:]:
            gfx.text(12, y, line)
            y += 23
        draw_footer(width, height, "Enter accept   Esc cancel   Backspace delete")
        gfx.refresh()
        key = wait_key()
        if key == gfx.KEY_ESCAPE:
            return None
        if key in (KEY_ENTER, KEY_LF):
            return clean_line(value, limit)
        if key in (KEY_BACKSPACE, KEY_DELETE):
            value = value[:-1]
        elif text_key(key) and len(value) < limit:
            value += chr(key)
    return None


def ensure_tree(path):
    path = normalize_path(path)
    current = ""
    for part in path.split("/"):
        if not part:
            continue
        current += "/" + part
        try:
            solaros.storage.mkdir(current)
        except OSError:
            pass


def writable_folder(path):
    """Verify a proposed vault with a real create/write/remove cycle."""
    ensure_tree(path)
    probe = normalize_path(path + "/.flint-write-test.tmp")
    if not probe:
        return False
    remove_file(probe)
    try:
        with open(probe, "w") as output:
            output.write("ok")
            output.flush()
        return file_size(probe) == 2
    except Exception:
        return False
    finally:
        remove_file(probe)


def remove_file(path):
    try:
        solaros.storage.remove(path)
        return True
    except OSError:
        return False


def atomic_json(path, value):
    atomic_write(path, value, True)


def atomic_text(path, value):
    value = checked_document(value)
    atomic_write(path, value, False)
    return value


def checked_document(value):
    if not isinstance(value, str):
        raise ValueError("note text must be a string")
    value = clean_document(value, len(value))
    if utf8_size(value, MAX_NOTE_BYTES) > MAX_NOTE_BYTES:
        raise ValueError("note exceeds the {} KB limit".format(MAX_NOTE_BYTES // 1024))
    return value


def atomic_write(path, value, json_value):
    temporary = path + ".tmp"
    backup = path + ".bak"
    with open(temporary, "w") as output:
        if json_value:
            json.dump(value, output)
        else:
            output.write(value)
        output.flush()
    remove_file(backup)
    had_original = True
    try:
        solaros.storage.rename(path, backup)
    except OSError:
        had_original = False
    try:
        solaros.storage.rename(temporary, path)
    except Exception:
        if had_original:
            try:
                solaros.storage.rename(backup, path)
            except OSError:
                pass
        raise


def default_config():
    return {"root": DEFAULT_ROOT, "daily_folder": DEFAULT_DAILY_FOLDER,
            "daily_template": "# {date}\n\n"}


def load_config():
    value = load_json_recovery(CONFIG_PATH, "root")
    config = default_config()
    if isinstance(value, dict):
        root = normalize_path(value.get("root", ""))
        if root.startswith("/") and root != "/" and len(root) <= MAX_PATH - 90:
            config["root"] = root.rstrip("/")
        folder = safe_filename(value.get("daily_folder", ""), DEFAULT_DAILY_FOLDER)
        config["daily_folder"] = folder
        template = clean_document(value.get("daily_template", ""), MAX_BLOCK)
        if template:
            config["daily_template"] = template
    return config


def load_index(root):
    path = index_storage_path(root)
    value = load_json_recovery(path, "notes")
    if value is None and path != INDEX_PATH:
        legacy = load_json_recovery(INDEX_PATH, "notes")
        migrated = normalize_index(legacy, root)
        if migrated.get("notes"):
            value = legacy
    index = normalize_index(value, root)
    if value is not None and path != INDEX_PATH and file_size(path) < 0:
        try:
            atomic_json(path, index)
        except Exception:
            pass
    return index


def index_storage_path(root):
    root = normalize_path(root)
    if root == DEFAULT_ROOT:
        return INDEX_PATH
    digest = binascii.hexlify(hashlib.sha256(root.encode("utf-8")).digest())[:16].decode("ascii")
    return DATA_DIR + "/index-" + digest + ".json"


def load_json_recovery(path, required_key=None):
    for candidate in (path, path + ".tmp", path + ".bak"):
        try:
            with open(candidate, "r") as source:
                value = json.load(source)
            if (not isinstance(value, dict) or
                    (required_key is not None and required_key not in value)):
                continue
            if candidate != path:
                atomic_json(path, value)
            return value
        except Exception:
            continue
    return None


def save_config(config):
    atomic_json(CONFIG_PATH, config)


def save_index(index):
    root = index.get("root", "") if isinstance(index, dict) else ""
    atomic_json(index_storage_path(root) if root else INDEX_PATH, index)
    gc.collect()


def file_size(path):
    """Return a regular file's size without the unavailable os module."""
    try:
        with open(path, "rb") as source:
            source.seek(0, 2)
            return source.tell()
    except Exception:
        return -1


def read_note(path):
    found = False
    oversized = False
    for candidate in (path, path + ".tmp", path + ".bak"):
        size = file_size(candidate)
        if size < 0:
            continue
        found = True
        if size > MAX_NOTE_BYTES:
            oversized = True
            continue
        try:
            with open(candidate, "r") as source:
                value = source.read(MAX_NOTE_BYTES + 1)
            if len(value) > MAX_NOTE_BYTES:
                oversized = True
                continue
            value = clean_document(value)
            if candidate != path:
                atomic_text(path, value)
            return value
        except Exception:
            continue
    if oversized:
        raise ValueError("note exceeds the {} KB limit".format(MAX_NOTE_BYTES // 1024))
    raise OSError("file not found or unreadable" if found else "file not found")


def note_item(index, path):
    lowered = normalize_path(path).lower()
    for item in index.get("notes", []):
        if item.get("path", "").lower() == lowered:
            return item
    return None


def index_path(index, path, text=None):
    if text is None:
        text = read_note(path)
    item = metadata(path, text, file_size(path))
    upsert(index, item)
    return item


def register_folder(index, root, folder):
    """Remember a folder because SolarOS Python cannot enumerate directories."""
    folder = normalize_path(folder)
    root = normalize_path(root)
    folders = index.setdefault("folders", [])
    while folder and inside(root, folder) and folder != root:
        if folder not in folders:
            folders.append(folder)
        folder = dirname(folder)


def known_folders(index, root):
    result = {normalize_path(root): True}
    for folder in index.get("folders", []):
        register = normalize_path(folder)
        if register and inside(root, register):
            result[register] = True
    for item in index.get("notes", []):
        folder = dirname(item.get("path", ""))
        while folder and inside(root, folder):
            result[folder] = True
            if folder == root:
                break
            folder = dirname(folder)
    return result


def progress(width, height, title, current, total, detail=""):
    gfx.clear(gfx.WHITE)
    draw_header(width, title, detail, "{}/{}".format(current, total) if total else str(current))
    x = 18
    y = height // 2 - 11
    bar_width = max(40, width - 36)
    gfx.color(gfx.BLACK)
    gfx.rect(x, y, bar_width, 22)
    if total:
        filled = max(0, min(bar_width - 4, (bar_width - 4) * current // total))
        if filled:
            gfx.fill_rect(x + 2, y + 2, filled, 18)
    draw_footer(width, height, "Please wait")
    gfx.refresh()


def rebuild_index(width, height, root, old_index):
    global REFRESH_ERRORS
    REFRESH_ERRORS = []
    root = normalize_path(root)
    discovered = []
    folders = []
    pending = [root]
    seen_directories = {}
    seen_paths = {}
    scan_errors = 0
    while pending and len(discovered) < MAX_NOTES:
        folder = pending.pop()
        key = folder.lower()
        if key in seen_directories:
            continue
        seen_directories[key] = True
        try:
            cursor = None
            while True:
                page = solaros.storage.scandir(folder, cursor, 64)
                entries = page.get("entries", [])
                for entry in entries:
                    name = entry.get("name", "")
                    if not name or name in (".", ".."):
                        continue
                    path = normalize_path(folder.rstrip("/") + "/" + name)
                    if not inside(root, path):
                        continue
                    if entry.get("is_dir"):
                        folders.append(path)
                        pending.append(path)
                    elif entry.get("is_file") and is_note_path(path):
                        lowered = path.lower()
                        if lowered not in seen_paths:
                            seen_paths[lowered] = True
                            discovered.append(path)
                            if len(discovered) >= MAX_NOTES:
                                break
                if len(discovered) >= MAX_NOTES:
                    break
                cursor = page.get("next_cursor")
                if cursor is None:
                    break
        except Exception as error:
            scan_errors += 1
            if len(REFRESH_ERRORS) < 3:
                REFRESH_ERRORS.append(basename(folder) + ": " +
                                      clean_line(str(error) or repr(error), 60))
    result = {"version": 1, "notes": [],
              "favorites": list(old_index.get("favorites", [])),
              "recent": list(old_index.get("recent", [])),
              "folders": folders, "root": root}
    discovered.sort(key=lambda value: value.lower())
    old_notes = {item.get("path", "").lower(): item
                 for item in old_index.get("notes", [])}
    failures = scan_errors
    for position, path in enumerate(discovered):
        gc.collect()
        try:
            index_path(result, path)
        except Exception as error:
            failures += 1
            if len(REFRESH_ERRORS) < 3:
                REFRESH_ERRORS.append(basename(path) + ": " +
                                      clean_line(str(error) or repr(error), 60))
            old = old_notes.get(path.lower())
            has_copy = any(file_size(candidate) >= 0 for candidate in
                           (path, path + ".tmp", path + ".bak"))
            if old is not None and has_copy:
                try:
                    upsert(result, old)
                except ValueError:
                    pass
        if position % 4 == 0 or position + 1 == len(discovered):
            progress(width, height, "Scanning vault", position + 1,
                     len(discovered), basename(path))
        if position % 8 == 7:
            gc.collect()
    valid = {item.get("path", "").lower(): True for item in result["notes"]}
    result["favorites"] = [path for path in result["favorites"] if path.lower() in valid]
    result["recent"] = [path for path in result["recent"] if path.lower() in valid][:20]
    save_index(result)
    old_index.clear()
    old_index.update(result)
    return old_index, failures, len(discovered) >= MAX_NOTES


def refresh_failure_text(failures):
    if not failures:
        return ""
    value = " {} file{} could not be read.".format(
        failures, "" if failures == 1 else "s")
    if REFRESH_ERRORS:
        value += " " + "; ".join(REFRESH_ERRORS)
    return value


def list_folder(root, folder, index):
    entries = []
    for path in known_folders(index, root):
        if path != folder and dirname(path) == folder:
            entries.append({"kind": "folder", "path": path,
                            "label": "[+] " + basename(path)})
    for item in index.get("notes", []):
        path = item.get("path", "")
        if dirname(path) == folder:
            entries.append({"kind": "note", "path": path,
                            "label": item.get("title", stem(path))})
    entries.sort(key=lambda item: (0 if item["kind"] == "folder" else 1,
                                   item["label"].lower()))
    return entries


def unique_note_path(folder, title, extension=".md"):
    base = safe_filename(title) or "Untitled"
    extension = extension if extension in (".md", ".markdown", ".txt") else ".md"
    candidate = normalize_path(folder + "/" + base + extension)
    if not candidate:
        raise ValueError("the note path is too long")
    number = 2
    while any(file_size(candidate + suffix) >= 0 for suffix in ("", ".tmp", ".bak")) and number < 1000:
        candidate = normalize_path(folder + "/" + base + "-" + str(number) + extension)
        if not candidate:
            raise ValueError("the note path is too long")
        number += 1
    if any(file_size(candidate + suffix) >= 0 for suffix in ("", ".tmp", ".bak")):
        raise ValueError("could not choose an unused filename")
    return candidate


def unique_import_path(root, source):
    name = basename(source)
    lowered = name.lower()
    extension = ".markdown" if lowered.endswith(".markdown") else ".txt" if lowered.endswith(".txt") else ".md"
    base = safe_filename(stem(name)) or "Imported"
    candidate = normalize_path(root + "/" + base + extension)
    number = 2
    while candidate and file_size(candidate) >= 0 and number < 1000:
        candidate = normalize_path(root + "/" + base + "-" + str(number) + extension)
        number += 1
    if not candidate or file_size(candidate) >= 0:
        raise ValueError("could not choose an unused filename")
    return candidate


def add_file(source, config, index):
    """Index an in-vault note or safely copy an external note into the vault."""
    source = normalize_path(source)
    if not source or not is_note_path(source):
        raise ValueError("the source must be a .md, .markdown, or .txt file")
    text = read_note(source)
    if len(index.get("notes", [])) >= MAX_NOTES and note_item(index, source) is None:
        raise ValueError("the vault index is full")
    root = config["root"]
    destination = source
    if not inside(root, source):
        ensure_tree(root)
        destination = unique_import_path(root, source)
        temporary = destination + ".tmp"
        remove_file(temporary)
        try:
            solaros.storage.copy(source, temporary)
            solaros.storage.rename(temporary, destination)
        except Exception:
            remove_file(temporary)
            raise
    try:
        index_path(index, destination, text)
        touch_recent(index, destination)
        save_index(index)
    except Exception as error:
        print("Flint copied the file, but could not update its index: " + str(error))
    return destination


def create_note(width, height, folder, index, title=None, content=None):
    if len(index.get("notes", [])) >= MAX_NOTES:
        message(width, height, "Vault full", "The index supports at most {} notes.".format(MAX_NOTES))
        return None
    if title is None:
        title = edit_line(width, height, "New note", "Title", "", 100)
    title = clean_line(title, 100)
    if not title:
        return None
    ensure_tree(folder)
    try:
        path = unique_note_path(folder, title)
        text = content if content is not None else "# " + title + "\n\n"
        atomic_text(path, text)
    except Exception as error:
        message(width, height, "Could not create note", str(error))
        return None
    try:
        index_path(index, path, clean_document(text))
        touch_recent(index, path)
        save_index(index)
    except Exception as error:
        message(width, height, "Note created", "The note is safe on disk, but its index could not be updated. Refresh the index later. " + str(error))
    return path


def render_block(block, columns):
    code = False
    start = 0
    while start <= len(block):
        end = block.find("\n", start)
        if end < 0:
            end = len(block)
        raw = block[start:end]
        stripped = raw.strip()
        if stripped.startswith("```"):
            code = not code
            if end == len(block):
                break
            start = end + 1
            continue
        style = "mono" if code else "normal"
        prefix = ""
        value = stripped
        if not code and value.startswith("#"):
            style = "heading"
            value = value.lstrip("#").strip()
        elif not code and value.startswith(">"):
            style = "quote"
            prefix = "> "
            value = value[1:].strip()
        elif not code and len(value) >= 2 and value[0] in ("-", "*", "+") and value[1] == " ":
            prefix = "- "
            value = value[2:]
        elif not code:
            dot = value.find(". ")
            if 0 < dot < 4 and all_digits(value[:dot]):
                prefix = value[:dot + 2]
                value = value[dot + 2:]
        if not code and len(value) >= 4 and value.startswith("**") and value.endswith("**"):
            style = "bold"
        is_rule = len(value) >= 3
        for character in value:
            if character not in "-_*":
                is_rule = False
                break
        if is_rule:
            yield ("-" * min(columns, 30), "mono")
        elif code:
            plain = raw.rstrip().replace("\t", "    ")
            if plain:
                for position in range(0, len(plain), columns):
                    yield (plain[position:position + columns], style)
            else:
                yield ("", style)
        else:
            plain = strip_inline(value)
            for line in wrap(prefix + plain, columns, 1400) or [""]:
                yield (line, style)
        if end == len(block):
            break
        start = end + 1


class RenderedDocument:
    """Compact rendered rows: one text buffer plus offsets and style bytes."""
    STYLE_NAMES = ("normal", "heading", "quote", "bold", "mono")

    def __init__(self, records):
        output = io.StringIO()
        self.offsets = []
        self.styles = bytearray()
        for value, style in records:
            self.offsets.append(output.tell())
            self.styles.append(self.STYLE_NAMES.index(style))
            output.write(value)
            output.write("\n")
        if not self.offsets:
            self.offsets.append(0)
            self.styles.append(2)
            output.write("Empty note\n")
        self.text = output.getvalue()
        output.close()

    def __len__(self):
        return len(self.offsets)

    def row(self, position):
        start = self.offsets[position]
        end = (self.offsets[position + 1] - 1
               if position + 1 < len(self.offsets) else len(self.text) - 1)
        return self.text[start:end], self.STYLE_NAMES[self.styles[position]]

    def __getitem__(self, key):
        if isinstance(key, slice):
            start = 0 if key.start is None else max(0, key.start)
            stop = len(self) if key.stop is None else min(len(self), key.stop)
            step = 1 if key.step is None else key.step
            return [self.row(position) for position in range(start, stop, step)]
        return self.row(key)


def iter_render_blocks(text):
    """Yield Markdown blocks without allocating a list for every source line."""
    text = clean_document(text)
    current = []
    in_fence = False
    start = 0
    while start <= len(text):
        end = text.find("\n", start)
        if end < 0:
            end = len(text)
        line = text[start:end]
        stripped = line.strip()
        if not stripped and not in_fence:
            if current:
                yield "\n".join(current).rstrip()
                current = []
        else:
            current.append(line.rstrip())
        if stripped.startswith("```"):
            in_fence = not in_fence
        if end == len(text):
            break
        start = end + 1
    if current:
        yield "\n".join(current).rstrip()


def rendered_document(text, columns):
    def records():
        first = True
        for block in iter_render_blocks(text):
            if not first:
                yield "", "normal"
            first = False
            for row in render_block(block, columns):
                yield row
    return RenderedDocument(records())


def draw_reader(width, height, item, lines, scroll, favorite, external=False):
    gfx.clear(gfx.WHITE)
    visible = max(1, (height - HEADER_H - FOOTER_H - 6) // 19)
    counter = ""
    if len(lines) > visible:
        counter = "{}-{} / {}".format(scroll + 1, min(len(lines), scroll + visible), len(lines))
    subtitle = ("External file" if external else "Favorite" if favorite else
                clip(item.get("path", ""), 60))
    draw_header(width, item.get("title", "Untitled"), subtitle, counter)
    y = HEADER_H + 19
    for line in lines[scroll:scroll + visible]:
        value, style = line
        gfx.color(gfx.DARK if style == "quote" else gfx.BLACK)
        if style == "heading":
            gfx.font(gfx.FONT_BOLD_16)
        elif style == "bold":
            gfx.font(gfx.FONT_BOLD_14)
        elif style == "mono":
            gfx.font(gfx.FONT_MONO_12)
        else:
            gfx.font(gfx.FONT_MONO_14)
        columns = max(5, (width - 18) // (6 if style == "mono" else 7))
        gfx.text(9, y, raw_clip(value, columns) if style == "mono" else clip(value, columns))
        y += 19
    draw_footer(width, height, "B browse  E edit  L links  A actions")
    gfx.refresh()


def discard_choice(width, height):
    result = choose(width, height, "Unsaved changes", ["Save changes", "Discard changes", "Keep editing"])
    return "save" if result == 0 else "discard" if result == 1 else "cancel"


def cursor_vertical(value, cursor, direction, preferred=None):
    line_start = value.rfind("\n", 0, cursor) + 1
    column = cursor - line_start if preferred is None else preferred
    if direction < 0:
        if line_start == 0:
            return cursor
        previous_end = line_start - 1
        previous_start = value.rfind("\n", 0, previous_end) + 1
        return min(previous_start + column, previous_end)
    line_end = value.find("\n", cursor)
    if line_end < 0:
        return cursor
    next_start = line_end + 1
    next_end = value.find("\n", next_start)
    if next_end < 0:
        next_end = len(value)
    return min(next_start + column, next_end)


def editor_window(value, cursor, columns, visible):
    """Build only the small raw-text window surrounding the caret."""
    span = max(columns * (visible + 3), 128)
    start = max(0, cursor - span // 2)
    end = min(len(value), start + span)
    if end == len(value):
        start = max(0, end - span)
    marker = "\x01"
    marked = value[start:cursor] + marker + value[cursor:end]
    lines = []
    caret_line = 0
    for source in marked.split("\n"):
        pieces = [source[position:position + columns]
                  for position in range(0, len(source), columns)] or [""]
        for piece in pieces:
            if marker in piece:
                caret_line = len(lines)
                piece = piece.replace(marker, "|")
            lines.append(piece)
    first = max(0, min(caret_line - visible // 2, len(lines) - visible))
    return lines[first:first + visible]


def edit_document(width, height, initial, limit=MAX_NOTE_BYTES, title="Edit note"):
    value = clean_document(initial, limit)
    cursor = len(value)
    byte_length = utf8_size(value)
    preferred_column = None
    while not solaros.should_exit():
        gfx.clear(gfx.WHITE)
        draw_header(width, title, "Raw Markdown", "{}/{} B".format(byte_length, limit))
        columns = max(8, (width - 24) // 8)
        visible = max(1, (height - HEADER_H - FOOTER_H - 8) // 19)
        gfx.color(gfx.BLACK)
        gfx.font(gfx.FONT_MONO_14)
        y = HEADER_H + 19
        for line in editor_window(value, cursor, columns, visible):
            gfx.text(10, y, line)
            y += 19
        draw_footer(width, height, "Ctrl+S save  Ctrl+B vault  Esc cancel")
        gfx.refresh()
        key = wait_key()
        if key == gfx.KEY_ESCAPE:
            return "cancel", value
        if key == KEY_CTRL_S:
            return "save", clean_document(value, limit)
        if key == KEY_CTRL_B:
            return "browse", clean_document(value, limit)
        if key in (KEY_ENTER, KEY_LF) and byte_length < limit:
            value = value[:cursor] + "\n" + value[cursor:]
            cursor += 1
            byte_length += 1
            preferred_column = None
        elif key == KEY_BACKSPACE:
            if cursor:
                byte_length -= utf8_size(value[cursor - 1:cursor])
                value = value[:cursor - 1] + value[cursor:]
                cursor -= 1
                preferred_column = None
        elif key == KEY_DELETE or key == getattr(gfx, "KEY_DELETE", -1003):
            if cursor < len(value):
                byte_length -= utf8_size(value[cursor:cursor + 1])
                value = value[:cursor] + value[cursor + 1:]
                preferred_column = None
        elif key == gfx.KEY_LEFT:
            cursor = max(0, cursor - 1)
            preferred_column = None
        elif key == gfx.KEY_RIGHT:
            cursor = min(len(value), cursor + 1)
            preferred_column = None
        elif key == gfx.KEY_UP:
            if preferred_column is None:
                preferred_column = cursor - (value.rfind("\n", 0, cursor) + 1)
            cursor = cursor_vertical(value, cursor, -1, preferred_column)
        elif key == gfx.KEY_DOWN:
            if preferred_column is None:
                preferred_column = cursor - (value.rfind("\n", 0, cursor) + 1)
            cursor = cursor_vertical(value, cursor, 1, preferred_column)
        elif key == getattr(gfx, "KEY_PAGE_UP", -1001):
            for unused in range(visible):
                if preferred_column is None:
                    preferred_column = cursor - (value.rfind("\n", 0, cursor) + 1)
                cursor = cursor_vertical(value, cursor, -1, preferred_column)
        elif key == getattr(gfx, "KEY_PAGE_DOWN", -1002):
            for unused in range(visible):
                if preferred_column is None:
                    preferred_column = cursor - (value.rfind("\n", 0, cursor) + 1)
                cursor = cursor_vertical(value, cursor, 1, preferred_column)
        elif key == getattr(gfx, "KEY_HOME", -1004):
            cursor = value.rfind("\n", 0, cursor) + 1
            preferred_column = None
        elif key == getattr(gfx, "KEY_END", -1005):
            end = value.find("\n", cursor)
            cursor = len(value) if end < 0 else end
            preferred_column = None
        elif key == 9 and byte_length <= limit - 4:
            value = value[:cursor] + "    " + value[cursor:]
            cursor += 4
            byte_length += 4
            preferred_column = None
        elif text_key(key):
            character = chr(key)
            size = utf8_size(character)
            if byte_length + size > limit:
                continue
            value = value[:cursor] + character + value[cursor:]
            cursor += 1
            byte_length += size
            preferred_column = None
    return "cancel", initial


def edit_block(width, height, initial):
    """Small-document wrapper retained for editing the daily-note template."""
    return edit_document(width, height, initial, MAX_BLOCK, "Edit daily template")


def save_note(width, height, path, text, index, root):
    try:
        text = atomic_text(path, text)
    except ValueError as error:
        message(width, height, "Note too large", str(error))
        return False
    except Exception as error:
        message(width, height, "Could not save", str(error))
        return False
    if inside(root, path):
        try:
            index_path(index, path, text)
            touch_recent(index, path)
            save_index(index)
        except Exception as error:
            message(width, height, "Note saved", "The note is safe on disk, but its index could not be updated. Refresh the index later. " + str(error))
    return True


def edit_note(width, height, path, text, index, root):
    original = text
    value = text
    while not solaros.should_exit():
        action, value = edit_document(width, height, value, MAX_NOTE_BYTES,
                                      "Edit: " + stem(path))
        if action == "save":
            if save_note(width, height, path, value, index, root):
                return "reader", read_note(path)
        elif action in ("cancel", "browse"):
            if value == original:
                return ("browse" if action == "browse" else "reader"), original
            choice = discard_choice(width, height)
            if choice == "save" and save_note(width, height, path, value, index, root):
                return ("browse" if action == "browse" else "reader"), read_note(path)
            if choice == "discard":
                return ("browse" if action == "browse" else "reader"), original
    return "reader", original


def note_list(width, height, title, items, index, root, subtitle=""):
    selected = 0
    while items and not solaros.should_exit():
        labels = []
        favorites = index.get("favorites", [])
        for item in items:
            marker = "* " if item.get("path") in favorites else ""
            labels.append(marker + item.get("title", stem(item.get("path", ""))))
        choice = choose(width, height, title, labels, selected, subtitle)
        if choice is None:
            return None
        selected = choice
        action = open_note_flow(width, height, items[selected]["path"], index, root)
        if action and action[0] == "browse":
            return action
        refreshed = []
        for old in items:
            current = note_item(index, old.get("path", ""))
            if current is not None:
                refreshed.append(current)
        items = refreshed
        selected = min(selected, max(0, len(items) - 1))
    if not items:
        message(width, height, title, "No notes found.")
    return None


def links_screen(width, height, text, current_path, index, root):
    links = link_items(text)
    if not links:
        message(width, height, "Links", "This note has no wiki links.")
        return None
    selected = 0
    while not solaros.should_exit():
        choice = choose(width, height, "Links", [item["label"] for item in links], selected)
        if choice is None:
            return None
        selected = choice
        link = links[selected]
        targets = resolve_links(index, link["target"], current_path)
        target = targets[0] if targets else None
        if len(targets) > 1:
            selected_target = choose(width, height, "Choose linked note",
                                     [item.get("path", item.get("title", "Untitled"))
                                      for item in targets])
            if selected_target is None:
                continue
            target = targets[selected_target]
        if target:
            return "open", target["path"], link.get("heading", "")
        elif confirm(width, height, "Missing note", "Create a note named " + link["target"] + "?"):
            path = create_note(width, height, dirname(current_path) if inside(root, current_path) else root,
                               index, link["target"])
            if path:
                return "open", path, link.get("heading", "")


def rename_note(width, height, path, text, item, index, root):
    old_title = item.get("title", stem(path))
    new_title = edit_line(width, height, "Rename note", "New title", old_title, 100)
    if not new_title or new_title == old_title:
        return path, text, item
    try:
        lowered = path.lower()
        extension = ".markdown" if lowered.endswith(".markdown") else ".txt" if lowered.endswith(".txt") else ".md"
        new_path = unique_note_path(dirname(path), new_title, extension)
    except Exception as error:
        message(width, height, "Could not rename", str(error))
        return path, text, item
    old_text = text
    text = rename_title_heading(text, new_title)
    linked_paths = {}
    for other in index.get("notes", []):
        if other.get("path") == path:
            continue
        for link in other.get("links", []):
            if title_key(stem(link)) not in (title_key(old_title), title_key(stem(path))):
                continue
            matches = resolve_links(index, link, other.get("path", ""))
            if (matches and matches[0].get("path") == path and
                    (len(matches) == 1 or "/" in link or
                     dirname(other.get("path", "")).lower() == dirname(path).lower())):
                linked_paths[other.get("path", "")] = True
                break
    try:
        solaros.storage.rename(path, new_path)
        if text != old_text:
            try:
                atomic_text(new_path, text)
                remove_file(path + ".bak")
                remove_file(path + ".tmp")
            except Exception:
                solaros.storage.rename(new_path, path)
                raise
        elif file_size(path + ".bak") >= 0 and file_size(new_path + ".bak") < 0:
            try:
                solaros.storage.rename(path + ".bak", new_path + ".bak")
            except OSError:
                pass
    except Exception as error:
        message(width, height, "Could not rename", str(error))
        return path, old_text, item
    was_favorite = path in index.get("favorites", [])
    remove_from_index(index, path)
    item = metadata(new_path, text, file_size(new_path))
    upsert(index, item)
    if was_favorite:
        index.setdefault("favorites", []).append(new_path)
    old_stem = stem(path)
    touched = 0
    link_failures = 0
    candidates = list(index.get("notes", []))
    for position, other in enumerate(candidates):
        if other.get("path") == new_path:
            continue
        if other.get("path", "") in linked_paths:
            try:
                other_text = read_note(other["path"])
                changed = rename_links(other_text, old_title, new_title)
                if old_stem.lower() != old_title.lower():
                    changed = rename_links(changed, old_stem, new_title)
                if changed != other_text:
                    atomic_text(other["path"], changed)
                    index_path(index, other["path"], changed)
                    touched += 1
            except Exception:
                link_failures += 1
        if position % 8 == 0:
            progress(width, height, "Updating links", position + 1, len(candidates), new_title)
    touch_recent(index, new_path)
    try:
        save_index(index)
    except Exception as error:
        message(width, height, "Index save failed", "The note was renamed, but the index could not be saved. Add it again later. " + str(error))
        return new_path, text, item
    if touched or link_failures:
        detail = "Updated links in {} note{}.".format(touched, "" if touched == 1 else "s")
        if link_failures:
            detail += " {} linked note{} could not be updated.".format(
                link_failures, "" if link_failures == 1 else "s")
        message(width, height, "Note renamed", detail)
    return new_path, text, item


def folder_picker(width, height, root, initial, index):
    folders = known_folders(index, root)
    folder = initial if inside(root, initial) and initial in folders else root
    while not solaros.should_exit():
        children = []
        for path in known_folders(index, root):
            if path != folder and dirname(path) == folder:
                children.append((basename(path), path))
        children.sort(key=lambda pair: pair[0].lower())
        options = ["Use this folder"] + ["[+] " + pair[0] for pair in children]
        if folder != root:
            options.insert(1, "[..] Parent")
        choice = choose(width, height, "Choose folder", options, 0, clip(folder, 55))
        if choice is None:
            return None
        if choice == 0:
            return folder
        offset = 2 if folder != root else 1
        if folder != root and choice == 1:
            folder = dirname(folder)
        else:
            folder = children[choice - offset][1]
    return None


def move_note(width, height, path, item, index, root):
    destination = folder_picker(width, height, root, dirname(path), index)
    if not destination or destination == dirname(path):
        return path, item
    new_path = normalize_path(destination + "/" + basename(path))
    if not new_path:
        message(width, height, "Cannot move", "The destination path is too long.")
        return path, item
    if file_size(new_path) >= 0:
        message(width, height, "Cannot move", "A file with that name already exists in the destination.")
        return path, item
    try:
        solaros.storage.rename(path, new_path)
    except Exception as error:
        message(width, height, "Could not move", str(error))
        return path, item
    if file_size(path + ".bak") >= 0 and file_size(new_path + ".bak") < 0:
        try:
            solaros.storage.rename(path + ".bak", new_path + ".bak")
        except OSError:
            pass
    remove_file(path + ".tmp")
    was_favorite = path in index.get("favorites", [])
    remove_from_index(index, path)
    item["path"] = new_path
    upsert(index, item)
    if was_favorite:
        index["favorites"].append(new_path)
    touch_recent(index, new_path)
    try:
        save_index(index)
    except Exception as error:
        message(width, height, "Index save failed", "The note was moved, but the index could not be saved. Add it again later. " + str(error))
    return new_path, item


def note_screen(width, height, path, index, root, initial_heading=""):
    path = normalize_path(path)
    try:
        text = read_note(path)
    except Exception as error:
        message(width, height, "Cannot open note", str(error))
        return None
    external = not inside(root, path)
    item = note_item(index, path) if not external else None
    if item is None:
        item = metadata(path, text, file_size(path))
        if not external:
            try:
                upsert(index, item)
            except ValueError:
                pass
    if not external:
        if touch_recent(index, path):
            try:
                save_index(index)
            except Exception:
                pass
    scroll = 0
    columns = max(10, (width - 18) // 7)
    lines = rendered_document(text, columns)
    if initial_heading:
        heading_key = clean_line(initial_heading).lower()
        for position, line in enumerate(lines):
            if line[1] == "heading" and clean_line(line[0]).lower() == heading_key:
                scroll = position
                break
    while not solaros.should_exit():
        visible = max(1, (height - HEADER_H - FOOTER_H - 6) // 19)
        scroll = max(0, min(scroll, max(0, len(lines) - visible)))
        draw_reader(width, height, item, lines, scroll,
                    path in index.get("favorites", []), external)
        key = wait_key()
        if key in (ord("a"), ord("A")):
            actions = ["Edit", "Open link", "Backlinks", "Browse vault"]
            action_keys = [ord("E"), ord("L"), ord("K"), ord("B")]
            if not external:
                actions.extend(["Toggle favorite", "Rename", "Move", "Delete"])
                action_keys.extend([ord("F"), ord("R"), ord("M"), ord("D")])
            action_choice = choose(width, height, "Note actions", actions)
            if action_choice is None:
                continue
            key = action_keys[action_choice]
        if key in (gfx.KEY_ESCAPE, gfx.KEY_LEFT, ord("q"), ord("Q")):
            return None
        if key in (gfx.KEY_UP, ord("k")):
            scroll = max(0, scroll - 1)
        elif key in (gfx.KEY_DOWN, ord("j")):
            scroll = min(max(0, len(lines) - visible), scroll + 1)
        elif key == getattr(gfx, "KEY_PAGE_UP", -1001):
            scroll = max(0, scroll - visible)
        elif key == getattr(gfx, "KEY_PAGE_DOWN", -1002):
            scroll = min(max(0, len(lines) - visible), scroll + visible)
        elif key in (ord("b"), ord("B")):
            return "browse", dirname(path) if inside(root, path) else root
        elif key in (ord("e"), ord("E")):
            action, new_text = edit_note(width, height, path, text, index, root)
            text = new_text
            item = metadata(path, text, file_size(path))
            if action == "browse":
                return "browse", dirname(path) if inside(root, path) else root
            scroll = 0
            lines = rendered_document(text, columns)
        elif key in (ord("l"), ord("L")):
            action = links_screen(width, height, text, path, index, root)
            if action:
                return (action[0], action[1], action[2] if len(action) > 2 else "", path)
        elif key == ord("K"):
            action = note_list(width, height, "Backlinks", backlinks(index, path), index, root,
                               "Notes linking here")
            if action and action[0] == "browse":
                return action
        elif key in (ord("f"), ord("F")) and not external:
            favorites = index.setdefault("favorites", [])
            old_favorites = list(favorites)
            if path in favorites:
                favorites.remove(path)
            else:
                favorites.append(path)
            try:
                save_index(index)
            except Exception as error:
                index["favorites"] = old_favorites
                message(width, height, "Could not update favorite", str(error))
        elif key in (ord("r"), ord("R")) and not external:
            path, text, item = rename_note(width, height, path, text, item, index, root)
            lines = rendered_document(text, columns)
        elif key in (ord("m"), ord("M")) and not external:
            path, item = move_note(width, height, path, item, index, root)
        elif key in (ord("d"), ord("D"), KEY_DELETE) and not external:
            if confirm(width, height, "Delete note", "Permanently delete " + item.get("title", basename(path)) + "?"):
                if remove_file(path):
                    remove_file(path + ".bak")
                    remove_file(path + ".tmp")
                    remove_from_index(index, path)
                    try:
                        save_index(index)
                    except Exception as error:
                        message(width, height, "Note deleted", "The file was deleted, but the index could not be saved. Refresh the index later. " + str(error))
                    return None
                message(width, height, "Could not delete", "The note could not be removed.")
        if key not in (gfx.KEY_UP, gfx.KEY_DOWN, ord("j"), ord("k"),
                       getattr(gfx, "KEY_PAGE_UP", -1001),
                       getattr(gfx, "KEY_PAGE_DOWN", -1002)):
            gc.collect()
    return None


def open_note_flow(width, height, path, index, root, heading=""):
    """Follow links iteratively so long browsing sessions do not grow the stack."""
    history = []
    current = path
    current_heading = heading
    while current and not solaros.should_exit():
        action = note_screen(width, height, current, index, root, current_heading)
        if action and action[0] == "open":
            history.append((action[3] if len(action) > 3 else current, ""))
            current = action[1]
            current_heading = action[2] if len(action) > 2 else ""
            continue
        if action and action[0] == "browse":
            return action
        if history:
            current, current_heading = history.pop()
            continue
        return None
    return None


def browser(width, height, root, index, initial=None):
    folders = known_folders(index, root)
    folder = initial if initial and inside(root, initial) and initial in folders else root
    selected = 0
    while not solaros.should_exit():
        entries = list_folder(root, folder, index)
        labels = [item["label"] for item in entries]
        if not labels:
            labels = ["(Empty folder)"]
        selection_state = [selected]
        choice = choose(width, height, "Vault browser", labels, selected,
                        clip(folder, 55), "N note  F folder  M rename  D delete  R refresh",
                        (ord("n"), ord("N"), ord("f"), ord("F"), ord("m"), ord("M"),
                         ord("d"), ord("D"), ord("r"), ord("R")), selection_state)
        selected = selection_state[0]
        if choice is None:
            if folder == root:
                return None
            folder = dirname(folder)
            selected = 0
            continue
        if choice in (-ord("n") - 1, -ord("N") - 1):
            path = create_note(width, height, folder, index)
            if path:
                action = open_note_flow(width, height, path, index, root)
                if action and action[0] == "browse":
                    folder = action[1]
            continue
        if choice in (-ord("f") - 1, -ord("F") - 1):
            name = edit_line(width, height, "New folder", "Folder name", "", 80)
            if name:
                path = normalize_path(folder + "/" + safe_filename(name, "Folder"))
                if file_size(path) >= 0 or path in known_folders(index, root):
                    message(width, height, "Already exists", "That name is already in this folder.")
                else:
                    try:
                        solaros.storage.mkdir(path)
                        register_folder(index, root, path)
                        save_index(index)
                    except Exception as error:
                        message(width, height, "Could not create folder", str(error))
            continue
        if choice in (-ord("r") - 1, -ord("R") - 1):
            index, failures, limited = rebuild_index(width, height, root, index)
            note = "Indexed {} notes.".format(len(index["notes"]))
            note += refresh_failure_text(failures)
            if limited:
                note += " The {}-note limit was reached.".format(MAX_NOTES)
            message(width, height, "Index refreshed", note)
            continue
        if choice in (-ord("m") - 1, -ord("M") - 1):
            if entries:
                selected = min(selected, len(entries) - 1)
                entry = entries[selected]
                if entry["kind"] == "folder":
                    rename_folder_from_browser(width, height, entry["path"], index, root)
                else:
                    message(width, height, "Rename folder", "Select a folder before pressing M. Notes can be renamed from their reading screen.")
            continue
        if choice in (-ord("d") - 1, -ord("D") - 1):
            if entries:
                selected = min(selected, len(entries) - 1)
                entry = entries[selected]
                if entry["kind"] == "folder":
                    delete_folder_from_browser(width, height, entry["path"], index, root)
                else:
                    delete_note_from_browser(width, height, entry["path"], index)
                selected = min(selected, max(0, len(list_folder(root, folder, index)) - 1))
            continue
        if not entries:
            continue
        selected = choice
        entry = entries[selected]
        if entry["kind"] == "folder":
            folder = entry["path"]
            selected = 0
        else:
            action = open_note_flow(width, height, entry["path"], index, root)
            if action and action[0] == "browse":
                folder = action[1] if inside(root, action[1]) else root
            entries = list_folder(root, folder, index)
            selected = min(selected, max(0, len(entries) - 1))
    return None


def date_value():
    try:
        now = solaros.time.datetime()
        if (isinstance(now, dict) and solaros.time.is_valid(now) and
                1 <= now.get("year", 0) <= 9999):
            return "{:04d}-{:02d}-{:02d}".format(now["year"], now["month"], now["day"])
    except Exception:
        pass
    return None


def daily_note(width, height, config, index):
    date = date_value()
    if not date:
        message(width, height, "Clock unavailable", "Set or synchronize the SolarOS clock before creating a daily note.")
        return None
    root = config["root"]
    folder = normalize_path(root + "/" + config["daily_folder"])
    path = normalize_path(folder + "/" + date + ".md")
    has_copy = any(file_size(candidate) >= 0 for candidate in
                   (path, path + ".tmp", path + ".bak"))
    if not has_copy:
        ensure_tree(folder)
        text = config["daily_template"].replace("{date}", date)
        try:
            atomic_text(path, text)
        except Exception as error:
            message(width, height, "Could not create daily note", str(error))
            return None
        try:
            index_path(index, path, text)
            save_index(index)
        except Exception as error:
            message(width, height, "Daily note created", "The note is safe on disk, but its index could not be updated. Refresh the index later. " + str(error))
    return path


def delete_note_from_browser(width, height, path, index):
    """Confirm and delete one indexed note plus its recovery copies."""
    item = note_item(index, path)
    title = item.get("title", stem(path)) if item else stem(path)
    if not confirm(width, height, "Delete note?", "Permanently delete " + title + "?"):
        return False
    if not remove_file(path):
        message(width, height, "Could not delete", "The note file could not be removed.")
        return False
    remove_file(path + ".bak")
    remove_file(path + ".tmp")
    remove_from_index(index, path)
    try:
        save_index(index)
    except Exception as error:
        message(width, height, "Note deleted", "The file was deleted, but the index could not be saved. Refresh the index later. " + str(error))
    return True


def remap_folder_paths(index, old_path, new_path):
    """Replace a folder prefix throughout all path-bearing index fields."""
    old_path = normalize_path(old_path)
    new_path = normalize_path(new_path)

    def changed(value):
        value = normalize_path(value)
        if value == old_path:
            return new_path
        if value.startswith(old_path + "/"):
            return new_path + value[len(old_path):]
        return value

    for item in index.get("notes", []):
        item["path"] = changed(item.get("path", ""))
    index["favorites"] = [changed(value) for value in index.get("favorites", [])]
    index["recent"] = [changed(value) for value in index.get("recent", [])]
    index["folders"] = [changed(value) for value in index.get("folders", [])]


def rename_folder_from_browser(width, height, path, index, root):
    path = normalize_path(path)
    if path == root or not inside(root, path):
        message(width, height, "Cannot rename folder", "The vault root cannot be renamed from Flint.")
        return False
    name = edit_line(width, height, "Rename folder", "New folder name", basename(path), 80)
    if not name:
        return False
    new_path = normalize_path(dirname(path) + "/" + safe_filename(name, "Folder"))
    if new_path == path:
        return False
    if new_path in known_folders(index, root) or file_size(new_path) >= 0:
        message(width, height, "Already exists", "That name is already in this folder.")
        return False
    try:
        solaros.storage.rename(path, new_path)
        remap_folder_paths(index, path, new_path)
        try:
            save_index(index)
        except Exception:
            solaros.storage.rename(new_path, path)
            remap_folder_paths(index, new_path, path)
            raise
    except Exception as error:
        message(width, height, "Could not rename folder", str(error))
        return False
    return True


def move_to_orphaned(path, destination, index, root):
    """Move an indexed note and its recovery files into the orphan folder."""
    lowered = path.lower()
    extension = (".markdown" if lowered.endswith(".markdown") else
                 ".txt" if lowered.endswith(".txt") else ".md")
    new_path = unique_note_path(destination, stem(path), extension)
    solaros.storage.rename(path, new_path)
    for suffix in (".bak", ".tmp"):
        if file_size(path + suffix) >= 0:
            try:
                solaros.storage.rename(path + suffix, new_path + suffix)
            except OSError:
                pass
    for item in index.get("notes", []):
        if item.get("path", "").lower() == lowered:
            item["path"] = new_path
            break
    index["favorites"] = [new_path if value.lower() == lowered else value
                          for value in index.get("favorites", [])]
    index["recent"] = [new_path if value.lower() == lowered else value
                       for value in index.get("recent", [])]
    register_folder(index, root, destination)
    return new_path


def delete_folder_from_browser(width, height, path, index, root):
    """Move contained notes to the recovery folder, then remove known folders."""
    path = normalize_path(path)
    root = normalize_path(root)
    if not path or path == root or not inside(root, path):
        message(width, height, "Cannot delete folder", "The vault root cannot be deleted from Flint.")
        return False
    notes = [item for item in index.get("notes", [])
             if inside(path, item.get("path", ""))]
    destination = normalize_path(root + "/orphaned notes")
    if path == destination and notes:
        message(width, height, "Cannot delete folder", "Move or delete the notes in the orphaned notes folder first.")
        return False
    detail = "Delete " + basename(path) + "?"
    if notes:
        detail += " Its {} note{} will be moved to /orphaned notes.".format(
            len(notes), "" if len(notes) == 1 else "s")
    if not confirm(width, height, "Delete folder?", detail):
        return False
    moved = 0
    failures = 0
    if notes:
        ensure_tree(destination)
        register_folder(index, root, destination)
    for position, item in enumerate(list(notes)):
        try:
            move_to_orphaned(item["path"], destination, index, root)
            moved += 1
        except Exception:
            failures += 1
        progress(width, height, "Moving orphaned notes", position + 1, len(notes),
                 item.get("title", stem(item.get("path", ""))))
        if position % 8 == 7:
            gc.collect()
    removed = {}
    folder_failures = 0
    if not failures:
        folders = [folder for folder in known_folders(index, root)
                   if folder == path or inside(path, folder)]
        folders.sort(key=lambda value: len(value), reverse=True)
        for folder in folders:
            try:
                solaros.storage.rmdir(folder)
                removed[folder.lower()] = True
            except OSError:
                folder_failures += 1
    if removed:
        index["folders"] = [folder for folder in index.get("folders", [])
                            if folder.lower() not in removed]
    index_error = None
    try:
        save_index(index)
    except Exception as error:
        index_error = error
    if failures:
        message(width, height, "Folder not deleted", "Moved {} note{}; {} could not be moved. The folder was kept.".format(
            moved, "" if moved == 1 else "s", failures))
        return False
    if folder_failures:
        message(width, height, "Folder not fully deleted", "The notes were moved, but an unindexed file or folder prevented removal.")
        return False
    if index_error is not None:
        message(width, height, "Folder deleted", "The folder was removed, but the index could not be saved. Refresh it later. " + str(index_error))
    elif moved:
        message(width, height, "Folder deleted", "Moved {} note{} to /orphaned notes.".format(
            moved, "" if moved == 1 else "s"))
    return True


def full_search(width, height, query, index):
    results = search_index(index, query)
    seen = {item["path"].lower(): True for item in results}
    notes = index.get("notes", [])
    key = query.lower()
    for position, item in enumerate(notes):
        if item["path"].lower() not in seen:
            try:
                text = read_note(item["path"])
                found = False
                overlap = max(0, len(key) - 1)
                offset = 0
                while offset < len(text):
                    if key in text[offset:offset + 512 + overlap].lower():
                        found = True
                        break
                    offset += 512
                if found:
                    results.append(item)
                    seen[item["path"].lower()] = True
            except Exception:
                pass
        if position % 8 == 0 or position + 1 == len(notes):
            progress(width, height, "Searching vault", position + 1, len(notes), query)
        if position % 8 == 7:
            gc.collect()
    results.sort(key=lambda item: item.get("title", "").lower())
    return results


def settings_screen(width, height, config, index):
    while not solaros.should_exit():
        options = ["Vault folder: " + config["root"],
                   "Daily folder: " + config["daily_folder"],
                   "Edit daily template", "Clear recent notes", "Refresh index"]
        choice = choose(width, height, "Flint settings", options)
        if choice is None:
            return index
        if choice == 0:
            value = edit_line(width, height, "Vault folder", "Absolute storage path", config["root"], MAX_PATH - 90)
            value = normalize_path(value)
            if value and value.startswith("/") and value != "/" and value != config["root"]:
                candidate = value.rstrip("/")
                if not confirm(width, height, "Change vault?", "Switching vaults hides the current index but does not delete its notes. Continue?"):
                    continue
                if not writable_folder(candidate):
                    message(width, height, "Cannot use vault", "That folder could not be created or written. The current vault was not changed.")
                    continue
                old_root = config["root"]
                config["root"] = candidate
                try:
                    save_config(config)
                    new_index = load_index(candidate)
                    index = new_index
                except Exception as error:
                    config["root"] = old_root
                    try:
                        save_config(config)
                    except Exception:
                        pass
                    message(width, height, "Could not change vault", str(error))
        elif choice == 1:
            value = edit_line(width, height, "Daily notes", "Folder within vault",
                              config["daily_folder"], 80)
            if value:
                old_value = config["daily_folder"]
                config["daily_folder"] = safe_filename(value, DEFAULT_DAILY_FOLDER)
                try:
                    save_config(config)
                except Exception as error:
                    config["daily_folder"] = old_value
                    message(width, height, "Could not save setting", str(error))
        elif choice == 2:
            action, value = edit_block(width, height, config["daily_template"])
            if action == "save" and value:
                old_value = config["daily_template"]
                config["daily_template"] = value + ("\n" if not value.endswith("\n") else "")
                try:
                    save_config(config)
                except Exception as error:
                    config["daily_template"] = old_value
                    message(width, height, "Could not save setting", str(error))
        elif choice == 3:
            old_recent = list(index.get("recent", []))
            index["recent"] = []
            try:
                save_index(index)
            except Exception as error:
                index["recent"] = old_recent
                message(width, height, "Could not clear recent", str(error))
        elif choice == 4:
            index, failures, limited = rebuild_index(width, height, config["root"], index)
            message(width, height, "Index refreshed", "Refreshed {} known notes.{}".format(
                len(index["notes"]), refresh_failure_text(failures)))
    return index


def recent_items(index):
    result = []
    for path in index.get("recent", []):
        item = note_item(index, path)
        if item:
            result.append(item)
    return result


def favorite_items(index):
    result = []
    for path in index.get("favorites", []):
        item = note_item(index, path)
        if item:
            result.append(item)
    result.sort(key=lambda item: item.get("title", "").lower())
    return result


def home(width, height, config, index):
    options = ["Today's note", "Browse vault", "New note", "Recent notes",
               "Favorites", "Search", "Tags", "Refresh index", "Settings"]
    selected = 0
    while not solaros.should_exit():
        choice = choose(width, height, "Flint", options, selected,
                        "{} notes  {} favorites".format(len(index.get("notes", [])),
                                                       len(index.get("favorites", []))),
                        "Enter choose   Esc exit")
        if choice is None:
            return
        selected = choice
        action = None
        root = config["root"]
        if choice == 0:
            path = daily_note(width, height, config, index)
            if path:
                action = open_note_flow(width, height, path, index, root)
        elif choice == 1:
            browser(width, height, root, index)
        elif choice == 2:
            path = create_note(width, height, root, index)
            if path:
                action = open_note_flow(width, height, path, index, root)
        elif choice == 3:
            action = note_list(width, height, "Recent notes", recent_items(index), index, root)
        elif choice == 4:
            action = note_list(width, height, "Favorites", favorite_items(index), index, root)
        elif choice == 5:
            query = edit_line(width, height, "Search vault", "Title, tag, link, or text", "", 100)
            if query:
                action = note_list(width, height, "Search results", full_search(width, height, query, index),
                                   index, root, query)
        elif choice == 6:
            tags = all_tags(index)
            if tags:
                tag_choice = choose(width, height, "Tags",
                                    ["#{} ({})".format(item["tag"], item["count"]) for item in tags])
                if tag_choice is not None:
                    tag = tags[tag_choice]["tag"]
                    action = note_list(width, height, "#" + tag, notes_for_tag(index, tag), index, root)
            else:
                message(width, height, "Tags", "No indexed tags were found.")
        elif choice == 7:
            index, failures, limited = rebuild_index(width, height, root, index)
            body = "Indexed {} notes.".format(len(index["notes"]))
            body += refresh_failure_text(failures)
            if limited:
                body += " The index limit was reached."
            message(width, height, "Index refreshed", body)
        elif choice == 8:
            index = settings_screen(width, height, config, index)
        if action and action[0] == "open":
            action = open_note_flow(width, height, action[1], index, root)
        if action and action[0] == "browse":
            browser(width, height, root, index, action[1])
        gc.collect()


def argument_path():
    for value in sys.argv[1:]:
        if isinstance(value, str) and not value.startswith("-"):
            return normalize_path(value)
    return None


def add_file_argument():
    for position, value in enumerate(sys.argv[1:]):
        if value == "--add-file":
            actual = position + 1
            return sys.argv[actual + 1] if actual + 1 < len(sys.argv) else ""
    return None


def add_list_argument():
    for position, value in enumerate(sys.argv[1:]):
        if value == "--add-list":
            actual = position + 1
            return sys.argv[actual + 1] if actual + 1 < len(sys.argv) else ""
    return None


def read_add_file_list(path):
    """Read a bounded newline-delimited list without loading it all at once."""
    if not path:
        raise ValueError("a list-file path is required")
    if file_size(path) > 16384:
        raise ValueError("the path list exceeds 16 KB")
    result = []
    with open(path, "r") as source:
        while len(result) < MAX_NOTES:
            line = source.readline()
            if not line:
                break
            line = normalize_path(line.strip())
            if line and not line.startswith("#"):
                result.append(line)
    return result


def main():
    ensure_tree(DATA_DIR)
    config = load_config()
    ensure_tree(config["root"])
    index = load_index(config["root"])
    source = add_file_argument()
    list_path = add_list_argument()
    if source is not None or list_path is not None:
        if source is not None and not source:
            print("Usage: flint --add-file /path/to/note.md")
            return
        try:
            sources = ([source] if source is not None else
                       read_add_file_list(list_path))
        except Exception as error:
            print("Flint could not read the path list: " + str(error))
            return
        added = 0
        failed = 0
        for item in sources:
            try:
                destination = add_file(item, config, index)
                print("Added to Flint: " + destination)
                added += 1
            except Exception as error:
                print("Flint could not add " + item + ": " + str(error))
                failed += 1
            gc.collect()
        if list_path is not None:
            print("Flint import finished: {} added, {} failed".format(added, failed))
        return
    gfx.begin()
    try:
        width, height = gfx.size()
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            gfx.clear(gfx.WHITE)
            gfx.color(gfx.BLACK)
            gfx.font(gfx.FONT_MONO_12)
            gfx.text(4, 14, clip("Flint needs a 200x140 display.", max(1, (width - 8) // 6)))
            gfx.refresh()
            wait_key()
            return
        path = argument_path()
        if path:
            if (is_note_path(path) and any(file_size(candidate) >= 0 for candidate in
                                           (path, path + ".tmp", path + ".bak"))):
                action = open_note_flow(width, height, path, index, config["root"])
                if action and action[0] == "browse":
                    browser(width, height, config["root"], index, action[1])
            else:
                message(width, height, "Cannot open file", "Flint accepts existing Markdown or text files.")
        home(width, height, config, index)
    finally:
        gfx.end()


if __name__ == "__main__":
    main()

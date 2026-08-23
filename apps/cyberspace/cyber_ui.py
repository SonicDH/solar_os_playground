"""SolarOS-native controller for all Cyberspace screen families."""

import solaros
from solaros import tui

from cyber_api import ApiError, CHAT_PAGE, CONTENT_PAGE
from cyber_components import (TABS, conversation_card, format_clock, guild_card,
                              irc_message_rows, message_bubble, post_card,
                              post_permalink, reply_card, room_card, tab_window)
from cyber_editor import EditorModel, login_form, multiline, single_line
from cyber_screens import (chat_lines, cmail_title, grouped_search,
                           guild_lines, item_title, note_lines,
                           notification_title, post_lines, profile_lines)
from cyber_screens import terminal_too_small
from cyber_sse import MessageWindow, RealtimeStream, SSEError
from cyber_text import (attachment_urls, plain_markdown, sanitize, title_text,
                        wrap_text)


KEY_ENTER = (10, 13)
KEY_J = ord("j")
KEY_K = ord("k")
KEY_Q = ord("q")
KEY_R = ord("r")
KEY_N = ord("n")
KEY_SEARCH = ord("/")
KEY_HELP = ord("?")
KEY_B = ord("b")
KEY_W = ord("w")
KEY_L = ord("l")
KEY_PAGE_UP = (getattr(tui, "KEY_PAGE_UP", 0x84),
               getattr(tui, "KEY_SHIFT_PAGE_UP", 0x9B))
KEY_PAGE_DOWN = (getattr(tui, "KEY_PAGE_DOWN", 0x85),
                 getattr(tui, "KEY_SHIFT_PAGE_DOWN", 0x9C))
KEY_TAB_LEFT = getattr(tui, "KEY_CTRL_LEFT", 0xA1)
KEY_TAB_RIGHT = getattr(tui, "KEY_CTRL_RIGHT", 0xA2)
MIN_COLS = 36
MIN_ROWS = 13


class _TabChange(Exception):
    def __init__(self, index):
        self.index = index


class _ExitApp(Exception):
    pass


def _list_data(document):
    if not isinstance(document, dict):
        return [], None
    data = document.get("data")
    if isinstance(data, list):
        return data, document.get("cursor")
    return [], document.get("cursor")


def _draw_select_row(items, index, screen_row, cols, formatter, selected):
    if index < 0 or index >= len(items):
        return
    item = items[index]
    label = formatter(item)
    if item.get("_heading"):
        label = "-- {} --".format(item["_heading"])
    marker = "> " if selected else "  "
    label = (marker + label)[:cols]
    attr = (tui.INVERSE | getattr(tui, "BOLD", 0)) if selected else tui.NORMAL
    tui.addstr(screen_row, 0, label, attr)


class Controller:
    def __init__(self, client):
        self.client = client
        self.me = None
        self.status = ""
        self.active_tab = 0
        self.tabs_active = False

    @staticmethod
    def _utc_now():
        try:
            return solaros.time.utc_datetime()
        except (AttributeError, OSError, TypeError, ValueError):
            return None

    @staticmethod
    def _localize_datetime(value):
        try:
            return solaros.time.utc_to_local(value)
        except (AttributeError, OSError, TypeError, ValueError):
            return value

    def run(self):
        self._require_terminal()
        if not self._authenticate():
            return
        self.tabs_active = True
        try:
            self.me = self.client.profile()
        except (ApiError, OSError, ValueError, TypeError):
            self.me = None
        while not solaros.should_exit() and self.client.id_token:
            try:
                action = getattr(self, "screen_" + TABS[self.active_tab][1])
                action()
            except _TabChange as change:
                self.active_tab = change.index % len(TABS)
            except _ExitApp:
                break
            except (ApiError, OSError, ValueError, TypeError) as error:
                self.error(error)

    def _require_terminal(self):
        while not solaros.should_exit():
            rows, cols = tui.size()
            if not terminal_too_small(rows, cols):
                return
            tui.clear()
            tui.title("Cyberspace")
            tui.addstr(max(1, rows // 2 - 1), 1,
                       "Terminal too small: {}x{}".format(cols, rows))
            tui.addstr(max(2, rows // 2), 1, "Need at least 36x13")
            tui.help("Esc exit")
            tui.refresh()
            if tui.getch(500) == tui.KEY_ESCAPE:
                raise KeyboardInterrupt

    def _authenticate(self):
        saved = self.client.saved_login()
        has_saved = self.client.has_saved_login()
        email = saved.get("email", "") if saved else ""
        remember = saved is not None
        while not solaros.should_exit():
            result = login_form(email, remember,
                                saved.get("email") if saved else None,
                                has_saved)
            if result is None:
                return False
            email = result.get("email", email)
            remember = bool(result.get("remember"))
            if result["action"] == "forget":
                self.client.forget_saved_login()
                saved = None
                has_saved = False
                email = ""
                remember = False
                self.notice("Saved login deleted. The password was never stored.")
                continue
            if result["action"] == "restore":
                try:
                    self.message("Login", ["Using saved login..."])
                    if self.client.restore():
                        return True
                except (ApiError, OSError, ValueError, TypeError) as error:
                    self.error(error)
                continue
            password = result.get("password", "")
            try:
                self.message("Login", ["Connecting..."])
                self.client.login(email, password, remember)
                password = None
                return True
            except (ApiError, OSError, ValueError, TypeError) as error:
                password = None
                self.error(error)
                if isinstance(error, ApiError) and error.code == "EMAIL_NOT_VERIFIED":
                    if self.confirm("Email not verified", ["Resend verification email?"]):
                        try:
                            self.client.resend_verification()
                            self.notice("Verification email sent")
                        except (ApiError, OSError) as resend_error:
                            self.error(resend_error)

    def _draw_chrome(self, title, help_text, detail=""):
        if detail:
            tui.title(title, detail)
        else:
            tui.title(title)
        if self.tabs_active:
            _, cols = tui.size()
            tui.fill(1, 0, 1, cols, " ", tui.NORMAL)
            for col, width, label, selected in tab_window(self.active_tab, cols):
                tui.tab(1, col, width, label, selected)
        tui.help(help_text)

    def _global_key(self, key, allow_quit=True):
        if not self.tabs_active:
            return False
        if key == KEY_TAB_LEFT:
            raise _TabChange(self.active_tab - 1)
        if key == KEY_TAB_RIGHT:
            raise _TabChange(self.active_tab + 1)
        if allow_quit and key == KEY_Q:
            raise _ExitApp()
        return False

    def menu(self, title, entries, help_text):
        labels = [{"name": label, "value": value} for label, value in entries]
        result = self.select(title, labels, help_text)
        return result.get("value") if result else None

    def _append_more(self, items, load_more):
        added = load_more() if load_more is not None else []
        if added:
            first = len(items)
            items.extend(added)
            self.status = "loaded more"
            return first
        self.status = "end"
        return None

    def select(self, title, items, help_text, extras="", formatter=item_title,
               refresh=None, load_more=None):
        cursor = 0
        top = 0
        dirty = True
        force_full = True
        rows = cols = body_rows = 0
        while not solaros.should_exit():
            self._require_terminal()
            if dirty:
                new_rows, new_cols = tui.size()
                if (new_rows, new_cols) != (rows, cols):
                    force_full = True
                rows, cols = new_rows, new_cols
                body_start = 2 if self.tabs_active else 1
                body_rows = max(1, rows - body_start - 1)
                if cursor >= len(items):
                    cursor = max(0, len(items) - 1)
                if cursor < top:
                    top = cursor
                if cursor >= top + body_rows:
                    top = cursor - body_rows + 1
                if force_full:
                    tui.clear()
                    self._draw_chrome(title, help_text)
                else:
                    tui.fill(body_start, 0, body_rows, cols, " ", tui.NORMAL)
                if not items:
                    tui.addstr(body_start + 1, 1, "No items")
                for row in range(body_rows):
                    index = top + row
                    if index >= len(items):
                        break
                    _draw_select_row(items, index, body_start + row, cols, formatter,
                                     index == cursor)
                suffix = "  " + self.status if self.status else ""
                tui.help((help_text + suffix)[:cols])
                self.status = ""
                tui.refresh()
                dirty = False
                force_full = False
            key = tui.getch(250)
            if key is None:
                continue
            old_cursor = cursor
            old_top = top
            content_changed = False
            if key == tui.KEY_ESCAPE:
                return None
            self._global_key(key)
            if key == tui.KEY_DOWN or key == KEY_J:
                if cursor < len(items) - 1:
                    cursor += 1
                elif load_more is not None:
                    first = self._append_more(items, load_more)
                    if first is not None:
                        cursor = first
                    content_changed = True
            elif key == tui.KEY_UP or key == KEY_K:
                cursor = max(0, cursor - 1)
            elif key == tui.KEY_PAGE_DOWN:
                if load_more is not None:
                    self._append_more(items, load_more)
                    content_changed = True
                cursor = min(max(0, len(items) - 1), cursor + body_rows)
            elif key == tui.KEY_PAGE_UP:
                cursor = max(0, cursor - body_rows)
            elif key in KEY_ENTER and items:
                if not items[cursor].get("_heading"):
                    return items[cursor]
            elif key == KEY_R and refresh is not None and "r" not in extras:
                refreshed = refresh()
                items[:] = refreshed or []
                cursor = top = 0
                content_changed = True
            elif key == KEY_HELP:
                self.viewer("Help", [help_text, "Arrows or j/k move.",
                                      "Enter opens. Escape goes back."], "Esc back")
                force_full = True
                content_changed = True
            elif isinstance(key, int) and key >= 0 and key <= 255 and chr(key).lower() in extras:
                return {"_action": chr(key).lower(), "_selected": items[cursor] if items else None}
            else:
                continue

            if cursor < top:
                top = cursor
            elif cursor >= top + body_rows:
                top = cursor - body_rows + 1
            if (not content_changed and cursor != old_cursor and top == old_top and
                    tui.size() == (rows, cols)):
                _draw_select_row(items, old_cursor, body_start + old_cursor - top, cols,
                                 formatter, False)
                _draw_select_row(items, cursor, body_start + cursor - top, cols,
                                 formatter, True)
                tui.refresh()
            elif content_changed or top != old_top:
                dirty = True

    def paged_select(self, title, loader, help_text, extras="", formatter=item_title):
        state = {"cursor": None, "more": True}

        def fetch(reset=False):
            if reset:
                state["cursor"] = None
                state["more"] = True
            if not state["more"]:
                return []
            document = loader(state["cursor"])
            records, cursor = _list_data(document)
            state["cursor"] = cursor
            state["more"] = cursor is not None
            return records

        items = fetch(True)
        return self.select(title, items, help_text, extras, formatter,
                           refresh=lambda: fetch(True), load_more=fetch)

    def _rich_line(self, row, col, width, segments):
        used = 0
        attrs = {"normal": tui.NORMAL, "bold": tui.BOLD,
                 "underline": tui.UNDERLINE}
        for text, style in segments:
            if used >= width:
                break
            clipped = sanitize(text).replace("\n", " ")[:width - used]
            if clipped:
                tui.addstr(row, col + used, clipped, attrs.get(style, tui.NORMAL))
                used += len(clipped)

    def _draw_card(self, item, row, cols, renderer, selected, max_height=None):
        width = max(4, cols)
        inner = max(1, width - 4)
        lines = renderer(item, inner)
        if max_height is not None:
            lines = lines[:max(1, max_height - 2)]
        height = len(lines) + 2
        border_attr = (tui.BOLD | tui.INVERSE) if selected else tui.NORMAL
        tui.box(row, 0, height, width, border_attr)
        for offset, segments in enumerate(lines):
            self._rich_line(row + 1 + offset, 2, inner, segments)
        return height

    def _card_layout(self, items, cursor, top, body_rows, cols, renderer):
        top = min(max(0, top), max(0, len(items) - 1))
        while True:
            positions = {}
            row = 0
            for index in range(top, len(items)):
                height = min(body_rows, len(renderer(items[index], max(1, cols - 4))) + 2)
                if row and row + height > body_rows:
                    break
                positions[index] = (row, height)
                row += height
                if row >= body_rows:
                    break
            if not items or cursor in positions:
                return top, positions
            if cursor < top:
                top = cursor
            else:
                top += 1

    def card_select(self, title, items, help_text, renderer, extras="",
                    refresh=None, load_more=None):
        cursor = 0
        top = 0
        dirty = True
        force_full = True
        previous_geometry = None
        rows = cols = body_rows = 0
        positions = {}
        while not solaros.should_exit():
            self._require_terminal()
            if dirty:
                rows, cols = tui.size()
                geometry = (rows, cols)
                if geometry != previous_geometry:
                    force_full = True
                body_start = 2 if self.tabs_active else 1
                body_rows = max(1, rows - body_start - 1)
                cursor = min(cursor, max(0, len(items) - 1))
                top, positions = self._card_layout(
                    items, cursor, top, body_rows, cols, renderer)
                if force_full:
                    tui.clear()
                    self._draw_chrome(title, help_text)
                else:
                    tui.fill(body_start, 0, body_rows, cols, " ", tui.NORMAL)
                if not items:
                    tui.addstr(body_start + 1, 1, "No items")
                for index, (offset, height) in positions.items():
                    self._draw_card(items[index], body_start + offset, cols,
                                    renderer, index == cursor, height)
                suffix = "  " + self.status if self.status else ""
                tui.help((help_text + suffix)[:cols])
                self.status = ""
                tui.refresh()
                dirty = False
                force_full = False
                previous_geometry = geometry
            key = tui.getch(250)
            if key is None:
                continue
            if key == tui.KEY_ESCAPE:
                return None
            self._global_key(key)
            old_cursor = cursor
            if key == tui.KEY_DOWN or key == KEY_J:
                if cursor < len(items) - 1:
                    cursor += 1
                elif load_more is not None:
                    first = self._append_more(items, load_more)
                    if first is not None:
                        cursor = first
                    dirty = True
            elif key == tui.KEY_UP or key == KEY_K:
                cursor = max(0, cursor - 1)
            elif key == tui.KEY_PAGE_DOWN:
                if load_more is not None:
                    self._append_more(items, load_more)
                    dirty = True
                cursor = min(max(0, len(items) - 1),
                             cursor + max(1, len(positions)))
            elif key == tui.KEY_PAGE_UP:
                cursor = max(0, cursor - max(1, len(positions)))
            elif key in KEY_ENTER and items:
                return items[cursor]
            elif key == KEY_R and refresh is not None and "r" not in extras:
                items[:] = refresh() or []
                cursor = top = 0
                dirty = True
            elif key == KEY_HELP:
                self.viewer("Help", [help_text, "Arrows or j/k select a card.",
                                      "Ctrl-Left/Right changes tabs."], "Esc back")
                force_full = True
                dirty = True
            elif (isinstance(key, int) and 0 <= key <= 255 and
                  chr(key).lower() in extras):
                return {"_action": chr(key).lower(),
                        "_selected": items[cursor] if items else None}
            else:
                continue

            if dirty or cursor == old_cursor:
                continue
            new_top, new_positions = self._card_layout(
                items, cursor, top, body_rows, cols, renderer)
            if new_top != top:
                top = new_top
                dirty = True
                continue
            body_start = 2 if self.tabs_active else 1
            for index, selected in ((old_cursor, False), (cursor, True)):
                if index in positions:
                    offset, height = positions[index]
                    attr = (tui.BOLD | tui.INVERSE) if selected else tui.NORMAL
                    tui.box(body_start + offset, 0, height, cols, attr)
            tui.refresh()
            positions = new_positions

    def paged_card_select(self, title, loader, help_text, renderer, extras=""):
        state = {"cursor": None, "more": True}

        def fetch(reset=False):
            if reset:
                state["cursor"] = None
                state["more"] = True
            if not state["more"]:
                return []
            document = loader(state["cursor"])
            records, cursor = _list_data(document)
            state["cursor"] = cursor
            state["more"] = cursor is not None
            return records

        items = fetch(True)
        return self.card_select(title, items, help_text, renderer, extras,
                                refresh=lambda: fetch(True), load_more=fetch)

    def viewer(self, title, lines, help_text="Esc back", action_keys=""):
        top = 0
        dirty = True
        force_full = True
        rows = cols = visible = 0
        while not solaros.should_exit():
            if dirty:
                new_rows, new_cols = tui.size()
                if (new_rows, new_cols) != (rows, cols):
                    force_full = True
                rows, cols = new_rows, new_cols
                body_start = 2 if self.tabs_active else 1
                visible = max(1, rows - body_start - 1)
                wrapped = []
                for line in lines:
                    wrapped.extend(wrap_text(line, max(1, cols - 2)) or [""])
                top = min(top, max(0, len(wrapped) - visible))
                if force_full:
                    tui.clear()
                    self._draw_chrome(title, help_text[:cols])
                else:
                    tui.fill(body_start, 0, visible, cols, " ", tui.NORMAL)
                for row in range(visible):
                    if top + row >= len(wrapped):
                        break
                    tui.addstr(body_start + row, 1, wrapped[top + row][:cols - 2])
                tui.refresh()
                dirty = False
                force_full = False
            key = tui.getch(250)
            if key is None:
                continue
            if key == tui.KEY_ESCAPE:
                return None
            self._global_key(key)
            if key == tui.KEY_DOWN or key == KEY_J:
                top = min(max(0, len(wrapped) - visible), top + 1)
            elif key == tui.KEY_UP or key == KEY_K:
                top = max(0, top - 1)
            elif key == tui.KEY_PAGE_DOWN:
                top = min(max(0, len(wrapped) - visible), top + visible)
            elif key == tui.KEY_PAGE_UP:
                top = max(0, top - visible)
            elif key == KEY_HELP:
                self.notice(help_text + "  Arrows or j/k scroll.")
                force_full = True
            elif key in KEY_ENTER and "\n" in action_keys:
                return "\n"
            elif isinstance(key, int) and key >= 0 and key <= 255 and chr(key).lower() in action_keys:
                return chr(key).lower()
            dirty = True

    def message(self, title, lines):
        rows, cols = tui.size()
        tui.clear()
        tui.title(title)
        for index, line in enumerate(lines[:max(1, rows - 3)]):
            tui.addstr(1 + index, 1, sanitize(line)[:max(1, cols - 2)])
        tui.refresh()

    def notice(self, text):
        self.message("Cyberspace", [text])
        tui.help("Press any key")
        tui.refresh()
        while not solaros.should_exit() and tui.getch(250) is None:
            pass

    def error(self, error):
        self.viewer("Error", [str(error)], "Esc back")

    def confirm(self, title, lines):
        key = self.viewer(title, list(lines) + ["", "Press y to confirm."],
                          "Y confirm  Esc cancel", "y")
        return key == "y"

    def prompt_topics(self, existing=None):
        value = single_line("Topics (comma separated)", ",".join(existing or []), 128)
        if value is None:
            return None
        topics = [part.strip().lower() for part in value.split(",") if part.strip()]
        if len(topics) > 3:
            raise ValueError("at most three topics")
        return topics

    # Home.
    def screen_feed(self):
        while True:
            result = self.paged_card_select(
                "Feed", lambda cursor: self.client.feed(cursor, CONTENT_PAGE),
                "Enter thread  r reply  b bookmark  w watch  l link",
                post_card, "n/rbwl")
            if result is None:
                return
            action = result.get("_action")
            if action == "n":
                self.create_post()
            elif action == "/":
                self.screen_search()
            elif action:
                self._thread_action(result.get("_selected") or {}, action)
            else:
                self.post_detail(result.get("postId"), result)

    def create_post(self, guild_slug=None):
        title = single_line("Title (optional)", "", 100)
        if title is None:
            return
        topics = self.prompt_topics()
        if topics is None:
            return
        content = multiline("New entry", "", 32768)
        if content is None or not content.strip():
            return
        if guild_slug:
            self.client.create_guild_post(guild_slug, content, title, topics)
        else:
            public = self.confirm("Public entry?", ["Allow viewing without login?"])
            nsfw = self.confirm("NSFW?", ["Mark this entry as sensitive content?"])
            self.client.create_post(content, title, topics, public, nsfw)
        self.notice("Entry created")

    def post_detail(self, post_id, cached=None):
        post = self.client.post(post_id) if post_id else cached
        if not post:
            return
        post_id = post.get("postId") or post_id

        def thread_card(item, width):
            if item.get("_card_kind") == "reply":
                return reply_card(item, width)
            return post_card(item, width)

        while True:
            post = self.client.post(post_id) if post_id else post
            post["_card_kind"] = "post"
            reply_document = self.client.replies(post_id, None, CONTENT_PAGE)
            replies, reply_cursor = _list_data(reply_document)
            for reply in replies:
                reply["_card_kind"] = "reply"
            items = [post] + replies

            def more_replies():
                nonlocal reply_cursor
                if reply_cursor is None:
                    return []
                document = self.client.replies(post_id, reply_cursor, CONTENT_PAGE)
                added, reply_cursor = _list_data(document)
                for reply in added:
                    reply["_card_kind"] = "reply"
                return added

            result = self.card_select(
                "Thread", items,
                "Enter read  r reply  b bookmark  w watch  l link  m more",
                thread_card, "rbwlm", load_more=more_replies)
            if result is None:
                return
            action = result.get("_action")
            if action:
                self._thread_action(result.get("_selected") or post, action, post)
            elif result.get("_card_kind") == "reply":
                self.reply_detail(result)
            else:
                key = self.viewer(
                    item_title(result), post_lines(result),
                    "r reply b bookmark w watch l link m more  Esc back",
                    "rbwlm")
                if key:
                    self._thread_action(result, key, post)

    def _thread_action(self, selected, action, post=None):
        post = post or selected
        post_id = post.get("postId") or selected.get("postId")
        is_reply = selected.get("_card_kind") == "reply" or bool(selected.get("replyId"))
        if action == "r":
            content = multiline("Reply", "", 32768)
            if content and content.strip():
                parent = selected.get("replyId") if is_reply else None
                self.client.create_reply(post_id, content, parent)
                self.notice("Reply posted")
        elif action == "b":
            target = selected.get("replyId") if is_reply else post_id
            self.client.bookmark(target, "reply" if is_reply else "post")
            self.notice("Bookmarked")
        elif action == "w":
            status = self.client.watch_status(post_id)
            if status.get("watching"):
                self.client.unwatch(post_id)
                self.notice("Watch removed")
            else:
                self.client.watch(post_id)
                self.notice("Watching thread")
        elif action == "l":
            link = post_permalink(post)
            if not link:
                self.notice("This entry has no public link")
            else:
                solaros.clipboard.set(link.encode("utf-8"))
                self.notice("Link copied")
        elif action == "m":
            if is_reply:
                self.reply_detail(selected)
            else:
                self.post_more(post)

    def post_more(self, item):
        actions = (("Author profile", "author"), ("Copy attachment", "copy"),
                   ("Edit my entry", "edit"), ("Delete my entry", "delete"),
                   ("Report entry", "report"))
        choice = self.menu("Entry actions", actions, "Enter choose  Esc back")
        if choice == "author":
            self.profile_detail(item.get("authorUsername"))
        elif choice == "copy":
            self.copy_attachment(item)
        elif choice == "edit":
            self.edit_post_fields(item)
        elif choice == "delete" and self.confirm("Delete entry?", ["This cannot be undone."]):
            self.client.delete_post(item["postId"])
            self.notice("Entry deleted")
        elif choice == "report":
            reason = multiline("Report reason (optional)", "", 500)
            if reason is not None and self.confirm("Submit report?", ["Reports cannot be withdrawn."]):
                self.client.flag_post(item["postId"], reason)
                self.notice("Report submitted")

    def edit_post_fields(self, item):
        field = self.menu("Edit entry", (("Content", "content"), ("Title", "title"),
                                         ("Topics", "topics"), ("Public", "isPublic"),
                                         ("NSFW", "isNSFW")), "Enter choose")
        if field == "content":
            value = multiline("Edit content", item.get("content") or "", 32768)
            if value is not None:
                self.client.edit_post(item["postId"], {"content": value})
        elif field == "title":
            value = single_line("Edit title", item.get("title") or "", 100)
            if value is not None:
                self.client.edit_post(item["postId"], {"title": value})
        elif field == "topics":
            value = self.prompt_topics(item.get("topics"))
            if value is not None:
                self.client.edit_post(item["postId"], {"topics": value})
        elif field in ("isPublic", "isNSFW"):
            self.client.edit_post(item["postId"], {field: not bool(item.get(field))})

    def reply_list(self, post_id):
        self.post_detail(post_id)

    def reply_detail(self, item):
        key = self.viewer("Reply by @" + sanitize(item.get("authorUsername") or "?"),
                          plain_markdown(item.get("content") or "").split("\n"),
                          "r reply b bookmark e edit d delete f report", "rbedf")
        if key == "r":
            content = multiline("Reply to reply", "", 32768)
            if content and content.strip():
                self.client.create_reply(item["postId"], content, item["replyId"])
        elif key == "b":
            self.client.bookmark(item["replyId"], "reply")
        elif key == "e":
            content = multiline("Edit reply", item.get("content") or "", 32768)
            if content is not None:
                self.client.edit_reply(item["replyId"], content)
        elif key == "d" and self.confirm("Delete reply?", ["This cannot be undone."]):
            self.client.delete_reply(item["replyId"])
        elif key == "f":
            reason = multiline("Report reason (optional)", "", 500)
            if reason is not None and self.confirm("Submit report?", ["Reports cannot be withdrawn."]):
                self.client.flag_reply(item["replyId"], reason)

    def screen_notifications(self):
        unread = None
        kinds = None
        while True:
            result = self.paged_select(
                "Notifications", lambda cursor: self.client.notifications(cursor, unread, kinds),
                "Enter open  a mark all  f filter  r refresh", "af",
                notification_title)
            if result is None:
                return
            action = result.get("_action")
            if action == "a":
                while True:
                    response = self.client.mark_all_notifications()
                    if not response.get("hasMore"):
                        break
                self.notice("Notifications marked read")
            elif action == "f":
                filter_choice = self.menu("Filter", (("All", "all"), ("Unread", "unread"),
                                                     ("Read", "read"), ("Types", "types")),
                                          "Enter choose")
                if filter_choice == "types":
                    value = multiline("Notification types", ",".join(kinds or []), 512)
                    if value is not None:
                        kinds = [part.strip() for part in value.replace("\n", "").split(",")
                                 if part.strip()][:20]
                else:
                    unread = False if filter_choice == "unread" else True if filter_choice == "read" else None
                    if filter_choice == "all":
                        kinds = None
            else:
                if not result.get("read"):
                    self.client.mark_notification(result["id"])
                target = result.get("targetId")
                if target:
                    self.post_detail(target)

    # Profiles and social graph.
    def screen_profile(self):
        self.me = self.client.profile()
        self.profile_detail(None, self.me)

    def profile_detail(self, username=None, cached=None):
        item = cached or self.client.profile(username)
        while item:
            own = self.me and item.get("userId") == self.me.get("userId")
            key = self.viewer(item_title(item), profile_lines(item),
                              "p posts r replies g guilds o follows f follow k poke e edit",
                              "prgofek")
            if key is None:
                return
            if key == "p":
                self.user_posts(item["username"])
            elif key == "r":
                self.user_replies(item["username"])
            elif key == "g":
                document = self.client.user_guilds(item.get("username"))
                rows, _ = _list_data(document)
                chosen = self.select("Guild memberships", rows, "Enter open")
                if chosen:
                    self.guild_detail(chosen["slug"])
            elif key == "o":
                kind = self.menu("Social graph", (("Followers", "followers"),
                                                   ("Following", "following")),
                                 "Enter choose")
                if kind:
                    self.follow_list(kind, item.get("userId"))
            elif key == "f" and not own:
                if self.confirm("Follow user?", ["Follow @{}?".format(item["username"])]):
                    self.client.follow(item["userId"])
            elif key == "k" and not own:
                if self.confirm("Poke user?", ["Pokes are limited to one per hour."]):
                    self.client.poke(item["username"])
            elif key == "e" and own:
                self.edit_profile(item)
            item = self.client.profile(username)

    def edit_profile(self, item):
        field = self.menu("Edit profile", (("Bio", "bio"), ("Pinned entry", "pinnedPostId"),
                                           ("Display name", "displayName"),
                                           ("Website URL", "websiteUrl"),
                                           ("Website name", "websiteName"),
                                           ("Website image URL", "websiteImageUrl"),
                                           ("Location name", "locationName"),
                                           ("Coordinates", "coordinates")),
                          "Enter choose")
        if not field:
            return
        if field == "coordinates":
            latitude = single_line("Latitude (blank clears)",
                                   str(item.get("locationLatitude") or ""), 32)
            if latitude is None:
                return
            longitude = single_line("Longitude (blank clears)",
                                    str(item.get("locationLongitude") or ""), 32)
            if longitude is None:
                return
            if latitude.strip() == "" and longitude.strip() == "":
                values = {"locationLatitude": None, "locationLongitude": None}
            else:
                values = {"locationLatitude": float(latitude),
                          "locationLongitude": float(longitude)}
            self.client.update_profile(values)
            self.me = self.client.profile()
            return
        limits = {"bio": 640, "pinnedPostId": 128, "displayName": 64,
                  "websiteUrl": 2048, "websiteName": 64,
                  "websiteImageUrl": 2048, "locationName": 64}
        value = multiline("Edit " + field, item.get(field) or "", limits[field])
        if value is not None:
            self.client.update_profile({field: value or None})
            self.me = self.client.profile()

    def user_posts(self, username):
        result = self.paged_select("@{} entries".format(username),
                                   lambda cursor: self.client.user_posts(username, cursor),
                                   "Enter open  Esc back")
        if result:
            self.post_detail(result.get("postId"), result)

    def user_replies(self, username):
        result = self.paged_select("@{} replies".format(username),
                                   lambda cursor: self.client.user_replies(username, cursor),
                                   "Enter open  Esc back")
        if result:
            self.reply_detail(result)

    def screen_followers(self):
        self.follow_list("followers")

    def screen_following(self):
        self.follow_list("following")

    def follow_list(self, kind, user_id=None):
        result = self.paged_select(title_text(kind),
                                   lambda cursor: self.client.follows(kind, cursor, user_id),
                                   "Enter profile  u unfollow  Esc back" if user_id is None else
                                   "Enter profile  Esc back", "u" if user_id is None else "")
        if user_id is None and result and result.get("_action") == "u":
            selected = result.get("_selected") or {}
            if self.confirm("Unfollow?", [item_title(selected)]):
                self.client.unfollow(selected.get("id") or selected.get("followId"))
        elif result:
            self.profile_detail(result.get("username"))

    # Discovery.
    def screen_search(self):
        query = multiline("Search", "", 512)
        if not query:
            return
        query = " ".join(query.split())
        kind = self.menu("Search scope", (("All", "all"), ("Entries", "posts"),
                                          ("Replies", "replies"), ("Users", "users")),
                         "Enter choose")
        if not kind:
            return
        if kind == "all":
            document = self.client.search(query, "all")
            rows = grouped_search(document.get("data"))
            result = self.select("Search: " + query, rows, "Enter open  Esc back")
        else:
            result = self.paged_select("Search: " + query,
                                       lambda page: self.client.search(query, kind, page),
                                       "Enter open  Right more  Esc back")
        if not result:
            return
        kind = result.get("type")
        if kind == "user":
            self.profile_detail(result.get("username"))
        elif kind == "reply":
            self.reply_detail(result)
        else:
            self.post_detail(result.get("postId"), result)

    def screen_topics(self):
        document = self.client.topics()
        rows, _ = _list_data(document)
        topic = self.select("Topics", rows, "Enter feed  Esc back")
        if topic:
            slug = topic.get("slug") or topic.get("name")
            result = self.paged_card_select(
                "#" + slug, lambda cursor: self.client.topic_posts(slug, cursor),
                "Enter open  Esc back", post_card)
            if result:
                self.post_detail(result.get("postId"), result)

    def screen_guilds(self):
        result = self.paged_card_select(
            "Guilds", lambda cursor: self.client.guilds(cursor),
            "Enter open  r refresh  Ctrl-Left/Right tabs", guild_card)
        if result:
            self.guild_detail(result.get("slug"))

    def guild_detail(self, slug):
        def guild_thread_card(record, width):
            if record.get("_card_kind") == "guild":
                return guild_card(record, width)
            return post_card(record, width)

        while True:
            guild = self.client.guild(slug)
            guild["_card_kind"] = "guild"
            post_document = self.client.guild_posts(slug, None, CONTENT_PAGE)
            posts, post_cursor = _list_data(post_document)
            for post in posts:
                post["_card_kind"] = "post"

            def more_posts():
                nonlocal post_cursor
                if post_cursor is None:
                    return []
                document = self.client.guild_posts(slug, post_cursor, CONTENT_PAGE)
                added, post_cursor = _list_data(document)
                for post in added:
                    post["_card_kind"] = "post"
                return added

            result = self.card_select(
                item_title(guild), [guild] + posts,
                "Enter open  r reply  b bookmark  w watch  l link  n new",
                guild_thread_card, "rbwlnmjxp", load_more=more_posts)
            if result is None:
                return
            selected = result.get("_selected") if result.get("_action") else result
            action = result.get("_action")
            if not action:
                if selected.get("_card_kind") == "post":
                    self.post_detail(selected.get("postId"), selected)
                else:
                    self.viewer(item_title(guild), guild_lines(guild))
            elif action == "n":
                self.create_post(slug)
            elif action == "m":
                member = self.paged_select(
                    item_title(guild) + " members",
                    lambda cursor: self.client.guild_members(slug, cursor),
                    "Enter profile  Esc back")
                if member:
                    self.profile_detail(member.get("username"))
            elif action in ("j", "x", "p"):
                guild_action = {"j": "join", "x": "leave", "p": "promote"}[action]
                if self.confirm(title_text(guild_action) + " guild?", [item_title(guild)]):
                    self.client.guild_action(slug, guild_action)
            elif selected and selected.get("_card_kind") == "post":
                self._thread_action(selected, action)
            elif action == "l" and guild.get("link"):
                solaros.clipboard.set(sanitize(guild["link"]).encode("utf-8"))
                self.notice("Guild link copied")
            elif action in ("r", "b", "w", "l"):
                self.notice("Select a thread for that action")

    # Library.
    def screen_bookmarks(self):
        result = self.paged_select("Bookmarks", lambda cursor: self.client.bookmarks(cursor),
                                   "Enter open  d remove  Esc back", "d")
        if not result:
            return
        if result.get("_action") == "d":
            selected = result.get("_selected") or {}
            if self.confirm("Remove bookmark?", [item_title(selected)]):
                self.client.remove_bookmark(selected.get("id") or selected.get("bookmarkId"))
            return
        if result.get("type") == "reply" and result.get("replyId"):
            self.reply_detail(self.client.reply(result["replyId"]))
        elif result.get("postId"):
            self.post_detail(result["postId"])

    def screen_watches(self):
        result = self.paged_select("Watched Threads", lambda cursor: self.client.watches(cursor),
                                   "Enter open  u unwatch  Esc back", "u")
        if result and result.get("_action") == "u":
            selected = result.get("_selected") or {}
            self.client.unwatch(selected.get("postId"))
        elif result:
            self.post_detail(result.get("postId"))

    def screen_notes(self):
        while True:
            result = self.paged_select("Journal", lambda cursor: self.client.notes(cursor),
                                       "Enter open  n new note  Esc back", "n")
            if result is None:
                return
            if result.get("_action") == "n":
                content = multiline("New journal note", "", 32768)
                if content and content.strip():
                    topics = self.prompt_topics() or []
                    self.client.create_note(content, topics)
            else:
                self.note_detail(result.get("id") or result.get("noteId"), result)

    def note_detail(self, note_id, cached=None):
        item = self.client.note(note_id) if note_id else cached
        key = self.viewer("Journal note", note_lines(item),
                          "e edit r revisions d delete  Esc back", "erd")
        if key == "e":
            content = multiline("Edit journal note", item.get("content") or "", 32768)
            if content is not None:
                topics = self.prompt_topics(item.get("topics"))
                if topics is not None:
                    self.client.update_note(note_id, content, topics)
        elif key == "r":
            result = self.paged_select("Note revisions",
                                       lambda cursor: self.client.note_revisions(note_id, cursor),
                                       "Enter view  Esc back")
            if result:
                revision = result.get("revision") or result.get("revisionNumber")
                self.viewer("Revision {}".format(revision),
                            note_lines(self.client.note(note_id, revision)))
        elif key == "d" and self.confirm("Delete note?", ["All revisions are soft-deleted."]):
            self.client.delete_note(note_id)

    # Settings.
    def screen_settings(self):
        settings = self.client.settings()
        fields = (("Filter NSFW", "filterNSFW"),
                  ("Show follower count", "showFollowerCount"),
                  ("Hide images in feed", "hideImagesInFeed"),
                  ("Hide audio in feed", "hideAudioInFeed"),
                  ("Auto-watch on reply", "autoWatchOnReply"),
                  ("Default public entry", "defaultPublicPost"))
        items = [{"name": "{}: {}".format(label, "on" if settings.get(key) else "off"),
                  "field": key} for label, key in fields]
        items.extend(({"name": "Notification types...", "field": "notifications"},
                      {"name": "Followed topics...", "field": "followedTopics"},
                      {"name": "Muted topics...", "field": "mutedTopics"},
                      {"name": "Time display: {}".format(settings.get("timeDisplayFormat") or
                                                         "default"),
                       "field": "timeDisplayFormat"},
                      {"name": "Logout and forget saved login...", "field": "logout"}))
        result = self.select("Settings", items, "Enter edit  Esc back")
        if result:
            key = result["field"]
            if key == "logout":
                self.screen_logout()
            elif key == "notifications":
                values = settings.get("notifications") or {}
                rows = [{"name": "{}: {}".format(name, "on" if enabled else "off"),
                         "type": name, "enabled": enabled}
                        for name, enabled in sorted(values.items())]
                chosen = self.select("Notification settings", rows, "Enter toggle  Esc back")
                if chosen:
                    updated = dict(values)
                    updated[chosen["type"]] = not chosen["enabled"]
                    self.client.update_settings({"notifications": updated})
            elif key in ("followedTopics", "mutedTopics"):
                value = multiline(result["name"].rstrip("."),
                                  ",".join(settings.get(key) or []), 512)
                if value is not None:
                    topics = [part.strip().lower() for part in value.replace("\n", "").split(",")
                              if part.strip()]
                    self.client.update_settings({key: topics})
            elif key == "timeDisplayFormat":
                value = single_line("Time display format",
                                    settings.get(key) or "", 64)
                if value is not None:
                    self.client.update_settings({key: value})
            else:
                self.client.update_settings({key: not bool(settings.get(key))})

    def screen_logout(self):
        if self.confirm("Logout?", ["This also deletes remembered login data."]):
            self.client.logout()
            self.notice("Logged out")

    # Messaging.
    def screen_cmail(self):
        document = self.client.cmail()
        rows, _ = _list_data(document)
        now = self._utc_now()

        def render_conversation(item, width):
            return conversation_card(item, width, now)

        def refresh():
            refreshed, _ = _list_data(self.client.cmail())
            return refreshed

        while True:
            result = self.card_select(
                "Email", rows,
                "Enter chat  n new conversation  r refresh  Ctrl-Left/Right tabs",
                render_conversation, "n", refresh=refresh)
            if result is None:
                return
            if result.get("_action") == "n":
                username = single_line("Recipient username", "", 20)
                if username:
                    conversation = self.client.start_cmail(username)
                    self.chat("cmail", conversation["conversationId"],
                              conversation.get("otherUser", {}).get("username") or username)
            else:
                other = result.get("otherUser") or {}
                self.chat("cmail", result["conversationId"],
                          other.get("displayName") or other.get("username") or "C-Mail")

    def screen_circ(self):
        document = self.client.circ_rooms()
        rows, _ = _list_data(document)
        now = self._utc_now()

        def render_room(item, width):
            return room_card(item, width, now)

        room = self.card_select(
            "IRC", rows,
            "Enter room  r refresh  Ctrl-Left/Right tabs", render_room,
            refresh=lambda: _list_data(self.client.circ_rooms())[0])
        if room:
            self.chat("circ", room.get("id") or room.get("slug"),
                      room.get("name") or room.get("slug"), room)

    def chat(self, kind, identifier, title, room=None):
        node = "dm_messages" if kind == "cmail" else "chat_messages"
        stream = RealtimeStream(self.client.http, self.client.rtdb_url,
                                self.client.id_token, node, identifier)
        window = MessageWindow()
        reveal = set()
        composer = EditorModel("", 190)
        composer_view = 0
        reconnect_at = None
        typing_active = False
        heartbeat_ms = 30000
        next_heartbeat = 0
        next_typing_poll = 0
        typing_status = ""
        last_input_ms = 0
        room_users = []
        next_users_poll = 0
        older_cursor = None
        scroll = 0
        body_dirty = True
        force_full = True
        rows = cols = body_rows = 0
        geometry = None
        render_cache = {}

        def activity():
            nonlocal typing_active, next_heartbeat, heartbeat_ms, last_input_ms
            now_ms = solaros.time.uptime_ms()
            last_input_ms = now_ms
            if kind == "cmail":
                if not typing_active or now_ms >= next_heartbeat:
                    response = self.client.cmail_typing(identifier, True)
                    heartbeat_ms = int(response.get("heartbeatMs", 3000))
                    next_heartbeat = now_ms + heartbeat_ms
                    typing_active = True
            else:
                if now_ms >= next_heartbeat:
                    epoch = self.client._now()
                    response = self.client.circ_presence(
                        identifier, epoch * 1000 if epoch is not None else None)
                    heartbeat_ms = int(response.get("heartbeatMs", heartbeat_ms))
                    next_heartbeat = now_ms + heartbeat_ms

        def editor_tick():
            nonlocal typing_active, next_heartbeat, heartbeat_ms
            now_ms = solaros.time.uptime_ms()
            if kind == "cmail" and typing_active and now_ms - last_input_ms >= 2500:
                self.client.cmail_typing(identifier, False)
                typing_active = False
            elif kind == "circ" and now_ms >= next_heartbeat:
                response = self.client.circ_presence(identifier)
                heartbeat_ms = int(response.get("heartbeatMs", heartbeat_ms))
                next_heartbeat = now_ms + heartbeat_ms

        def is_mine(record):
            from_user = record.get("from") or {}
            if not isinstance(from_user, dict):
                from_user = {}
            username = (record.get("senderUsername") or record.get("username") or
                        from_user.get("username"))
            user_id = record.get("senderId") or record.get("userId")
            if self.me:
                if username and username == self.me.get("username"):
                    return True
                if user_id and user_id == self.me.get("userId"):
                    return True
            return False

        def chat_detail():
            parts = []
            if kind == "circ":
                slug = (room or {}).get("slug") or (room or {}).get("handle") or identifier
                parts.append("#" + sanitize(slug))
                parts.append("{} online".format(len(room_users) or
                                                (room or {}).get("onlineCount", 0)))
            if typing_status:
                parts.append("typing...")
            if stream.handle is None:
                parts.append("reconnecting")
            if scroll:
                parts.append("{} messages back".format(scroll))
            if self.status:
                parts.append(self.status)
            return "  ".join(parts)

        def draw_composer():
            nonlocal composer_view
            input_top = rows - 4
            width = max(1, cols - 4)
            tui.input(input_top + 1, 2, width, "", composer.text,
                      composer.cursor, composer_view, tui.INVERSE, False)

        def render_record(record):
            shown = record.get("id") in reveal
            attachments = record.get("attachments")
            if isinstance(attachments, list):
                attachment_key = tuple(
                    (item.get("type"), item.get("url"), item.get("src"))
                    for item in attachments if isinstance(item, dict))
            else:
                attachment_key = ()
            audio = record.get("audioAttachment")
            audio_key = audio.get("src") if isinstance(audio, dict) else None
            style = record.get("style")
            if isinstance(style, list):
                style = tuple(style)
            from_user = record.get("from")
            from_username = (from_user.get("username")
                             if isinstance(from_user, dict) else None)
            mine = is_mine(record)
            signature = (
                cols, shown, mine, record.get("timestamp"), record.get("createdAt"),
                record.get("senderUsername"), record.get("username"),
                record.get("senderId"), record.get("userId"), from_username,
                record.get("content"), record.get("body"), record.get("text"),
                record.get("deleted"), record.get("isAction"), style,
                attachment_key, record.get("imageUrl"), record.get("gifUrl"),
                record.get("websiteUrl"), audio_key)
            cache_key = str(record.get("id") or "")
            cached = render_cache.get(cache_key)
            if cached is not None and cached[0] == signature:
                return cached[1]
            timestamp = format_clock(record.get("timestamp") or
                                     record.get("createdAt"),
                                     self._localize_datetime)
            if kind == "circ":
                lines = irc_message_rows(record, cols, shown, timestamp)
                rendered = (lines, len(lines), 0, cols, False)
            else:
                bubble_width = max(18, min(cols - 2, (cols * 3) // 4))
                lines = message_bubble(record, max(1, bubble_width - 4),
                                       mine, shown, timestamp)
                column = max(0, cols - bubble_width) if mine else 0
                rendered = (lines, len(lines) + 2, column, bubble_width, True)
            if len(render_cache) >= 96 and cache_key not in render_cache:
                render_cache.clear()
            render_cache[cache_key] = (signature, rendered)
            return rendered

        def record_height(record):
            _, raw_height, _, _, _ = render_record(record)
            return min(body_rows, raw_height)

        def page_size():
            """Return the message count in the page ending at this position."""
            records = window.records()[-80:]
            end = max(0, len(records) - scroll)
            used = 0
            count = 0
            for record in reversed(records[:end]):
                height = record_height(record)
                if count and used + height > body_rows:
                    break
                used += height
                count += 1
                if used >= body_rows:
                    break
            return max(1, count)

        def newer_page_size():
            """Return the message count in the full page after this one."""
            records = window.records()[-80:]
            start = max(0, len(records) - scroll)
            used = 0
            count = 0
            for record in records[start:]:
                height = record_height(record)
                if count and used + height > body_rows:
                    break
                used += height
                count += 1
                if used >= body_rows:
                    break
            return max(1, count)

        def maximum_scroll():
            """Keep the oldest viewport full instead of showing one orphan row."""
            records = window.records()[-80:]
            used = 0
            count = 0
            for record in records:
                height = record_height(record)
                if count and used + height > body_rows:
                    break
                used += height
                count += 1
                if used >= body_rows:
                    break
            return max(0, len(records) - max(1, count))

        def load_older():
            nonlocal older_cursor
            if older_cursor is None:
                self.status = "no older messages"
                return False
            if kind == "cmail":
                older = self.client.cmail_history(identifier, older_cursor, CHAT_PAGE)
            else:
                older = self.client.circ_history(identifier, older_cursor, CHAT_PAGE)
            records, older_cursor = _list_data(older)
            before = len(window.records())
            window.add_history(records)
            added = len(window.records()) - before
            self.status = "" if added else "no older messages"
            return added > 0

        def draw_body():
            nonlocal rows, cols, body_rows, force_full, geometry, scroll
            new_rows, new_cols = tui.size()
            new_geometry = (new_rows, new_cols)
            if new_geometry != geometry:
                force_full = True
            rows, cols = new_rows, new_cols
            body_start = 2
            input_top = rows - 4
            body_rows = max(1, input_top - body_start)
            if force_full:
                tui.clear()
                self._draw_chrome(title,
                                  "Enter send  PgUp/PgDn scroll  Ctrl-Left/Right tabs",
                                  chat_detail())
                tui.box(input_top, 0, 3, cols, tui.BOLD | tui.INVERSE)
                draw_composer()
            else:
                tui.title(title, chat_detail())
                tui.fill(body_start, 0, body_rows, cols, " ", tui.NORMAL)

            records = window.records()[-80:]
            scroll = min(scroll, maximum_scroll())
            end = max(0, len(records) - scroll)
            selected = []
            used = 0
            for record in reversed(records[:end]):
                lines, raw_height, col, block_width, boxed = render_record(record)
                height = min(body_rows, raw_height)
                if selected and used + height > body_rows:
                    break
                line_limit = max(1, height - 2) if boxed else height
                selected.append((record, lines[:line_limit], height, col,
                                 block_width, boxed))
                used += height
                if used >= body_rows:
                    break
            row = body_start + max(0, body_rows - used)
            for record, lines, height, col, block_width, boxed in reversed(selected):
                if boxed:
                    tui.box(row, col, height, block_width,
                            tui.BOLD if is_mine(record) else tui.NORMAL)
                for offset, segments in enumerate(lines):
                    line_row = row + 1 + offset if boxed else row + offset
                    line_col = col + 2 if boxed else col
                    line_width = max(1, block_width - 4) if boxed else block_width
                    self._rich_line(line_row, line_col, line_width, segments)
                row += height
            if not records:
                tui.addstr(body_start + body_rows // 2, 2, "No messages yet")
            tui.refresh()
            force_full = False
            geometry = new_geometry

        try:
            stream.open()
            window.start_reconcile()
            for event, payload in stream.validate():
                window.queue_live(event, payload)
            if kind == "cmail":
                history = self.client.cmail_history(identifier, limit=CHAT_PAGE)
                self.client.cmail_read(identifier)
            else:
                presence = self.client.circ_presence(identifier)
                heartbeat_ms = int(presence.get("heartbeatMs", 30000))
                next_heartbeat = solaros.time.uptime_ms() + heartbeat_ms
                history = self.client.circ_history(identifier, limit=CHAT_PAGE)
                self.client.circ_read(identifier)
            records, older_cursor = _list_data(history)
            window.reconcile(records)
            stream.connected()
            while not solaros.should_exit():
                chrome_dirty = False
                now_ms = solaros.time.uptime_ms()
                if kind == "cmail" and now_ms >= next_typing_poll:
                    status = self.client.cmail_typing_status(identifier)
                    new_typing_status = "typing" if status.get("typing") else ""
                    if new_typing_status != typing_status:
                        typing_status = new_typing_status
                        chrome_dirty = True
                    next_typing_poll = now_ms + 3000
                if kind == "circ" and now_ms >= next_heartbeat:
                    self.client.circ_presence(identifier)
                    next_heartbeat = now_ms + heartbeat_ms
                if kind == "circ" and now_ms >= next_users_poll:
                    new_room_users, _ = _list_data(self.client.circ_users(identifier))
                    if len(new_room_users) != len(room_users):
                        chrome_dirty = True
                    room_users = new_room_users
                    next_users_poll = now_ms + 30000
                if reconnect_at is not None and now_ms >= reconnect_at:
                    try:
                        stream.token = self.client.id_token
                        stream.open()
                        window.start_reconcile()
                        for event, payload in stream.validate():
                            window.queue_live(event, payload)
                        if kind == "cmail":
                            history = self.client.cmail_history(identifier, limit=CHAT_PAGE)
                        else:
                            history = self.client.circ_history(identifier, limit=CHAT_PAGE)
                        records, older_cursor = _list_data(history)
                        window.reconcile(records)
                        stream.connected()
                        reconnect_at = None
                        body_dirty = True
                    except (SSEError, ApiError, OSError):
                        delay = stream.retry_delay()
                        reconnect_at = now_ms + delay if delay is not None else None
                        chrome_dirty = True
                if stream.handle is not None:
                    try:
                        stream_events = stream.read(0)
                        content_changed = False
                        for event, payload in stream_events:
                            if window.queue_live(event, payload):
                                content_changed = True
                        if content_changed:
                            body_dirty = True
                    except SSEError as error:
                        stream.close()
                        if str(error) == "auth_revoked" or "401" in str(error):
                            self.client.refresh()
                            stream.token = self.client.id_token
                        delay = stream.retry_delay()
                        reconnect_at = now_ms + delay if delay is not None else None
                        chrome_dirty = True
                if body_dirty:
                    draw_body()
                    body_dirty = False
                elif chrome_dirty:
                    tui.title(title, chat_detail())
                    tui.refresh()
                key = tui.getch(250)
                if key is None:
                    editor_tick()
                    continue
                if key == tui.KEY_ESCAPE:
                    return
                self._global_key(key, False)
                if key in KEY_PAGE_UP:
                    target = scroll + page_size()
                    maximum = maximum_scroll()
                    if target >= maximum and older_cursor is not None:
                        load_older()
                        maximum = maximum_scroll()
                    scroll = min(maximum, target)
                    body_dirty = True
                elif key in KEY_PAGE_DOWN:
                    scroll = max(0, scroll - newer_page_size())
                    if scroll == 0:
                        self.status = ""
                    body_dirty = True
                elif key in KEY_ENTER:
                    content = composer.text
                    if content and content.strip():
                        if kind == "cmail":
                            self.client.send_cmail(identifier, content)
                            typing_active = False
                        else:
                            self.client.send_circ(identifier, content)
                        if kind == "cmail":
                            history = self.client.cmail_history(identifier, limit=CHAT_PAGE)
                        else:
                            history = self.client.circ_history(identifier, limit=CHAT_PAGE)
                        records, refreshed_cursor = _list_data(history)
                        if refreshed_cursor is not None:
                            older_cursor = refreshed_cursor
                        window.reconcile(records)
                        composer.text = ""
                        composer.cursor = 0
                        composer_view = 0
                        scroll = 0
                        body_dirty = True
                    draw_composer()
                    tui.refresh()
                elif key == 15:  # Ctrl-O: older history
                    before = len(window.records())
                    if load_older():
                        scroll += max(1, len(window.records()) - before)
                    body_dirty = True
                elif key == 21 and kind == "circ":  # Ctrl-U: users
                    users, _ = _list_data(self.client.circ_users(identifier))
                    self.select("Room users", users, "Esc back")
                    force_full = True
                    body_dirty = True
                elif key == 18:  # Ctrl-R: reconnect
                    stream.reconnect_count = 0
                    reconnect_at = solaros.time.uptime_ms()
                    tui.title(title, chat_detail())
                    tui.refresh()
                else:
                    width = max(1, cols - 4)
                    old_text = composer.text
                    value, cursor, composer_view, _ = tui.input_edit(
                        composer.text, composer.cursor, composer_view, key, width, 191)
                    composer.text = value
                    composer.cursor = cursor
                    if value != old_text:
                        activity()
                    draw_composer()
                    tui.refresh()
        finally:
            stream.close()
            try:
                if kind == "cmail" and typing_active:
                    self.client.cmail_typing(identifier, False)
                elif kind == "circ":
                    self.client.circ_leave(identifier)
            except (ApiError, OSError):
                pass

    def chat_message_actions(self, kind, identifier, records, reveal):
        if not records:
            return
        selected = self.select("Messages", records, "Enter actions  Esc back")
        if not selected:
            return
        actions = [("Copy attachment URL", "copy"), ("Reveal spoiler", "reveal")]
        if kind == "circ":
            actions.extend((("Delete my message", "delete"), ("Report message", "report")))
        choice = self.menu("Message actions", tuple(actions), "Enter choose  Esc back")
        if choice == "copy":
            self.copy_attachment(selected)
        elif choice == "reveal":
            reveal.add(selected.get("id"))
        elif choice == "delete" and self.confirm("Delete message?", ["This cannot be undone."]):
            self.client.delete_circ(identifier, selected["id"])
        elif choice == "report":
            reason = multiline("Report reason (optional)", "", 500)
            if reason is not None and self.confirm("Submit report?", ["Reports cannot be withdrawn."]):
                self.client.flag_circ(identifier, selected["id"], reason)

    def copy_attachment(self, item):
        links = attachment_urls(item)
        if not links:
            self.notice("No attachment URL")
            return
        rows = [{"name": "[{}] {}".format(label, url), "url": url}
                for label, url in links]
        chosen = self.select("Attachments", rows, "Enter copy  Esc back")
        if chosen:
            solaros.clipboard.set(chosen["url"].encode("utf-8"))
            self.notice("URL copied")

"""Pure layout models for the compact Cyberspace TUI."""

from cyber_text import (attachment_urls, decode_art, plain_markdown, sanitize,
                        style_names, wrap_text)


TABS = (
    ("Feed", "feed"),
    ("Notifications", "notifications"),
    ("Email", "cmail"),
    ("IRC", "circ"),
    ("Journal", "notes"),
    ("Bookmarks", "bookmarks"),
    ("Guilds", "guilds"),
    ("Topics", "topics"),
    ("Profile", "profile"),
    ("Settings", "settings"),
)


_LOGO = (
    "   ___     _             ___",
    "  / __|  _| |__  ___ _ _/ __|_ __  __ _ __ ___",
    " | (_| || | '_ \\/ -_) '_\\__ \\ '_ \\/ _` / _/ -_)",
    "  \\___\\_, |_.__/\\___|_| |___/ .__/\\__,_\\__\\___|",
    "      |__/                  |_|",
)


def logo_lines(width):
    """Return the readable ASCII Cyberspace wordmark when it fits."""
    if width >= max(len(row) for row in _LOGO):
        return list(_LOGO)
    return ["CYBERSPACE"]


def tab_window(active, width):
    """Return visible tab cells as (column, width, label, selected)."""
    active = min(max(0, active), len(TABS) - 1)
    widths = [len(label) + 2 for label, _ in TABS]
    left = active
    right = active + 1
    used = widths[active]
    while True:
        added = False
        if right < len(TABS) and used + widths[right] <= width:
            used += widths[right]
            right += 1
            added = True
        if left > 0 and used + widths[left - 1] <= width:
            left -= 1
            used += widths[left]
            added = True
        if not added:
            break
    cells = []
    column = 0
    for index in range(left, right):
        cell_width = widths[index]
        cells.append((column, cell_width, TABS[index][0], index == active))
        column += cell_width
    return cells


def _one_line(value, fallback=""):
    return sanitize(value or fallback).replace("\n", " ")


def _content_lines(value, width, limit=2):
    text = plain_markdown(value or "").replace("\n", " ")
    return (wrap_text(text, max(1, width)) or [""])[:limit]


def _epoch_datetime(value):
    """Convert a seconds/ms epoch to a small-int-safe UTC datetime dict."""
    text = str(value or "").strip()
    if not text or any(character < "0" or character > "9" for character in text):
        return None
    if len(text) >= 12:
        text = text[:-3]
    text = text.lstrip("0") or "0"
    quotient = []
    remainder = 0
    for character in text:
        current = remainder * 10 + ord(character) - ord("0")
        digit = current // 86400
        remainder = current % 86400
        if quotient or digit:
            quotient.append(chr(ord("0") + digit))
    days = int("".join(quotient) or "0")
    year = 1970
    while True:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        year_days = 366 if leap else 365
        if days < year_days:
            break
        days -= year_days
        year += 1
    month_days = [31, 29 if leap else 28, 31, 30, 31, 30,
                  31, 31, 30, 31, 30, 31]
    month = 1
    for count in month_days:
        if days < count:
            break
        days -= count
        month += 1
    return {"year": year, "month": month, "day": days + 1,
            "hour": remainder // 3600, "minute": (remainder % 3600) // 60,
            "second": remainder % 60}


def format_clock(value, localize=None):
    parts = _epoch_datetime(value)
    if parts is None:
        return ""
    if localize is not None:
        try:
            parts = localize(parts) or parts
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            pass
    return "{:02d}:{:02d}".format(int(parts["hour"]), int(parts["minute"]))


def human_activity(value, now=None):
    parts = _epoch_datetime(value)
    if parts is None:
        return _one_line(value)
    if isinstance(now, dict):
        def day_number(item):
            year = int(item["year"])
            prior = year - 1
            days = 365 * prior + prior // 4 - prior // 100 + prior // 400
            month_days = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
            for month in range(1, int(item["month"])):
                days += month_days[month - 1]
                if month == 2 and (year % 4 == 0 and
                                   (year % 100 != 0 or year % 400 == 0)):
                    days += 1
            return days + int(item["day"]) - 1

        delta = ((day_number(now) - day_number(parts)) * 86400 +
                 (int(now.get("hour", 0)) - int(parts["hour"])) * 3600 +
                 (int(now.get("minute", 0)) - int(parts["minute"])) * 60 +
                 int(now.get("second", 0)) - int(parts["second"]))
        if delta < 60:
            return "just now"
        if delta < 3600:
            return "{}m ago".format(delta // 60)
        if delta < 86400:
            return "{}h ago".format(delta // 3600)
        if delta < 604800:
            return "{}d ago".format(delta // 86400)
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d} UTC".format(
        parts["year"], parts["month"], parts["day"], parts["hour"],
        parts["minute"])


def post_card(item, width):
    """Return rich card rows; each segment is (text, style-name)."""
    width = max(1, width)
    author = _one_line(item.get("authorUsername") or item.get("username"), "?")
    timestamp = _one_line(item.get("createdAt") or item.get("updatedAt"))
    header = [("@" + author, "bold")]
    if timestamp:
        header.append(("  " + timestamp, "normal"))
    rows = [header]
    title = _one_line(item.get("title"))
    if title:
        rows.append([(title[:width], "bold")])
    for line in _content_lines(item.get("content"), width, 2):
        rows.append([(line, "normal")])
    topics = item.get("topics") or []
    badges = []
    if item.get("isGuildThread") and item.get("guildSlug"):
        badges.append("#" + _one_line(item.get("guildSlug")))
    badges.extend("#" + _one_line(topic) for topic in topics)
    if item.get("isNSFW"):
        badges.append("[NSFW]")
    replies = item.get("repliesCount")
    if replies is not None:
        badges.append("{} repl{}".format(replies, "y" if replies == 1 else "ies"))
    if badges:
        rows.append([("  ".join(badges)[:width], "normal")])
    return rows[:5]


def reply_card(item, width):
    author = _one_line(item.get("authorUsername") or item.get("username"), "?")
    parent = _one_line(item.get("parentUsername"))
    header = [("@" + author, "bold")]
    if parent:
        header.append(("  -> @" + parent, "normal"))
    rows = [header]
    for line in _content_lines(item.get("content"), max(1, width), 3):
        rows.append([(line, "normal")])
    return rows[:4]


def guild_card(item, width):
    name = _one_line(item.get("name") or item.get("slug"), "Guild")
    slug = _one_line(item.get("slug"))
    rows = [[(name[:width], "bold")]]
    meta = []
    if slug:
        meta.append("#" + slug)
    meta.append("{} members".format(item.get("memberCount", 0)))
    apprentices = item.get("apprenticeCount")
    if apprentices:
        meta.append("{} apprentices".format(apprentices))
    rows.append([("  ".join(meta)[:width], "normal")])
    bio = _content_lines(item.get("bio"), max(1, width), 1)[0]
    if bio:
        rows.append([(bio, "normal")])
    return rows


def conversation_card(item, width, now=None):
    other = item.get("otherUser") or {}
    name = _one_line(other.get("displayName") or other.get("username"),
                     "Unknown participant")
    username = _one_line(other.get("username"))
    header = [(name[:width], "bold")]
    if username and username != name:
        header.append(("  @" + username, "normal"))
    last = item.get("lastMessage") or {}
    if isinstance(last, dict):
        preview = last.get("content") or last.get("text") or last.get("body") or ""
        timestamp = (last.get("timestamp") or last.get("createdAt") or
                     item.get("lastMessageAt") or "")
    else:
        preview = last
        timestamp = item.get("lastMessageAt") or ""
    unread = item.get("unreadCount", 0)
    meta = []
    if timestamp:
        meta.append(human_activity(timestamp, now))
    if unread:
        meta.append("{} unread".format(unread))
    rows = [header, [(_content_lines(preview, max(1, width), 1)[0], "normal")]]
    if meta:
        rows.append([("  ".join(meta)[:width], "normal")])
    return rows


def room_card(item, width, now=None):
    name = _one_line(item.get("name") or item.get("slug"), "Room")
    slug = _one_line(item.get("slug") or item.get("handle") or item.get("id"))
    online = item.get("onlineCount")
    if online is None:
        online = item.get("usersOnline", item.get("userCount", 0))
    activity = (item.get("lastActivity") or item.get("lastMessageAt") or
                item.get("updatedAt") or "")
    rows = [[(name[:width], "bold")],
            [("#{}  {} online".format(slug, online)[:width], "normal")]]
    if activity:
        rows.append([("Last activity " + human_activity(activity, now), "normal")])
    return rows


def _message_content(item, reveal=False):
    if item.get("deleted"):
        content = "[deleted message]"
    else:
        styles = style_names(item)
        content = item.get("content") or item.get("body") or item.get("text") or ""
        if "art" in styles:
            content = decode_art(content)
        elif "spoiler" in styles and not reveal:
            content = "[spoiler hidden]"
        else:
            content = plain_markdown(content)
        visible = [value for value in styles if value not in ("art", "spoiler")]
        if visible:
            content = "[{}] {}".format("+".join(visible), content)
    lines = content.split("\n") if content else [""]
    for label, url in attachment_urls(item):
        if url != content.strip():
            lines.append("[{}] {}".format(label, url))
    return lines


def message_bubble(item, width, mine=False, reveal=False, timestamp=""):
    from_user = item.get("from") or {}
    if not isinstance(from_user, dict):
        from_user = {}
    sender = _one_line(item.get("senderUsername") or item.get("username") or
                       from_user.get("username"), "?")
    header = [(("you" if mine else "@" + sender), "bold")]
    if timestamp:
        header.append(("  " + timestamp, "normal"))
    rows = [header]
    for source in _message_content(item, reveal):
        for line in wrap_text(source, max(1, width)) or [""]:
            rows.append([(line, "normal")])
    return rows


def irc_message_rows(item, width, reveal=False, timestamp=""):
    """Render one cIRC message as compact IRC-client rows, without a box."""
    width = max(1, width)
    sender = _one_line(item.get("username") or item.get("senderUsername"), "?")
    action = bool(item.get("isAction"))
    prefix_text = "* {} ".format(sender) if action else "<{}>  ".format(sender)
    time_gap = 2 if timestamp else 0
    content_width = max(1, width - len(prefix_text) - len(timestamp) - time_gap)
    wrapped = []
    for source in _message_content(item, reveal):
        wrapped.extend(wrap_text(source, content_width) or [""])
    wrapped = wrapped or [""]
    rows = []
    for index, line in enumerate(wrapped):
        segments = []
        if index == 0:
            if action:
                segments.extend((("* ", "normal"), (sender, "bold"), (" ", "normal")))
            else:
                segments.extend((("<", "normal"), (sender, "bold"), (">  ", "normal")))
        else:
            segments.append((" " * len(prefix_text), "normal"))
        segments.append((line, "normal"))
        if timestamp and index == len(wrapped) - 1:
            used = len(prefix_text) + len(line)
            segments.append((" " * max(2, width - used - len(timestamp)), "normal"))
            segments.append((timestamp, "normal"))
        rows.append(segments)
    return rows


def post_permalink(item):
    author = _one_line(item.get("authorUsername") or item.get("username"))
    slug = _one_line(item.get("slug"))
    if not author or not slug:
        return None
    return "https://cyberspace.online/{}/{}".format(author, slug)

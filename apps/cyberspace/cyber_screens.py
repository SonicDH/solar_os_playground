"""Pure presentation helpers shared by Cyberspace screen families."""

from cyber_text import (attachment_urls, plain_markdown, render_message, sanitize,
                        title_text)
from cyber_components import TABS


# Compatibility names for older callers. The application now exposes the
# cyber-tui-style flat tab set directly rather than nested section menus.
ROOT_MENU = TABS
SUBMENUS = {}


def terminal_too_small(rows, cols):
    return rows < 13 or cols < 36


def item_title(item):
    if not isinstance(item, dict):
        return sanitize(item)
    if item.get("deleted"):
        return "[deleted]"
    for key in ("title", "name", "displayName", "username", "slug", "type"):
        if item.get(key):
            value = sanitize(item[key]).replace("\n", " ")
            if key == "displayName" and item.get("username"):
                value += " (@{})".format(sanitize(item["username"]))
            return value
    content = item.get("content") or item.get("lastMessage") or item.get("reason")
    if isinstance(content, dict):
        content = content.get("content") or content.get("text")
    if content:
        return plain_markdown(content).replace("\n", " ")[:96]
    for key in ("postId", "replyId", "conversationId", "id"):
        if item.get(key):
            return str(item[key])
    return "item"


def cmail_title(item):
    """Label a conversation by its other participant, never by message content."""
    if not isinstance(item, dict):
        return "Unknown participant"
    other = item.get("otherUser") or {}
    if not isinstance(other, dict):
        return "Unknown participant"
    display_name = sanitize(other.get("displayName") or "").replace("\n", " ")
    username = sanitize(other.get("username") or "").replace("\n", " ")
    if display_name and username:
        return "{} (@{})".format(display_name, username)
    if display_name:
        return display_name
    if username:
        return "@" + username
    return "Unknown participant"


def post_lines(item):
    lines = []
    author = item.get("authorUsername") or item.get("username") or "?"
    lines.append("By @{}".format(sanitize(author)))
    if item.get("createdAt"):
        lines.append(sanitize(item["createdAt"]))
    if item.get("topics"):
        lines.append("Topics: " + ", ".join(sanitize(value) for value in item["topics"]))
    flags = []
    if item.get("isPublic"):
        flags.append("public")
    if item.get("isNSFW"):
        flags.append("NSFW")
    if item.get("deleted"):
        flags.append("deleted")
    if flags:
        lines.append("[{}]".format(", ".join(flags)))
    lines.append("")
    lines.extend(plain_markdown(item.get("content") or "").split("\n"))
    for label, url in attachment_urls(item):
        lines.append("[{}] {}".format(label, url))
    replies = item.get("repliesCount")
    bookmarks = item.get("bookmarksCount")
    if replies is not None or bookmarks is not None:
        lines.append("")
        lines.append("Replies {}  Bookmarks {}".format(replies or 0, bookmarks or 0))
    return lines


def profile_lines(item):
    lines = ["@{}".format(sanitize(item.get("username") or "?"))]
    for label, key in (("Name", "displayName"), ("Guild", "guildName"),
                       ("Location", "locationName"), ("Website", "websiteUrl")):
        if item.get(key):
            lines.append("{}: {}".format(label, sanitize(item[key])))
    if item.get("bio"):
        lines.extend(("",) + tuple(plain_markdown(item["bio"]).split("\n")))
    lines.append("")
    lines.append("Followers {}  Following {}  Posts {}".format(
        item.get("followerCount", 0), item.get("followingCount", 0),
        item.get("postCount", 0)))
    return lines


def guild_lines(item):
    lines = [sanitize(item.get("name") or item.get("slug") or "Guild")]
    if item.get("icon"):
        lines[0] = sanitize(item["icon"]) + " " + lines[0]
    lines.append("{} members, {} apprentices".format(
        item.get("memberCount", 0), item.get("apprenticeCount", 0)))
    if item.get("role"):
        lines.append("Your role: " + sanitize(item["role"]))
    if item.get("bio"):
        lines.extend(("",) + tuple(plain_markdown(item["bio"]).split("\n")))
    if item.get("link"):
        lines.append("[website] " + sanitize(item["link"]))
    return lines


def note_lines(item):
    lines = []
    if item.get("revision") is not None:
        lines.append("Revision {}".format(item["revision"]))
    if item.get("topics"):
        lines.append("Topics: " + ", ".join(sanitize(value) for value in item["topics"]))
    lines.extend(("",) + tuple(plain_markdown(item.get("content") or "").split("\n")))
    return lines


def notification_title(item):
    actor = item.get("actorUsername") or "system"
    marker = " " if item.get("read") else "*"
    return "{}{} from {}".format(marker, sanitize(item.get("type") or "notice"),
                                  sanitize(actor))


def chat_lines(records, reveal=None):
    reveal = reveal or set()
    result = []
    for record in records:
        result.extend(render_message(record, record.get("id") in reveal).split("\n"))
    return result


def grouped_search(document):
    rows = []
    if not isinstance(document, dict):
        return rows
    for kind in ("users", "posts", "replies"):
        values = document.get(kind) or []
        if values:
            rows.append({"_heading": title_text(kind)})
            rows.extend(values)
    return rows

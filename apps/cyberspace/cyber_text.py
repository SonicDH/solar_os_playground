"""Bounded text, Markdown, attachment, and chat presentation helpers."""

try:
    import binascii
except ImportError:  # pragma: no cover - MicroPython alias
    import ubinascii as binascii


CONTROL_REPLACEMENT = " "


def utf8_len(text):
    return len(text.encode("utf-8"))


def sanitize(text):
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    result = []
    for character in text:
        code = ord(character)
        if character in "\n\t":
            result.append(character)
        elif code < 32 or code == 127 or (code >= 128 and code <= 159):
            result.append(CONTROL_REPLACEMENT)
        else:
            result.append(character)
    return "".join(result)


def title_text(text):
    """Return a small-ROM-compatible title without using str.title()."""
    result = []
    capitalize = True
    for character in sanitize(text):
        result.append(character.upper() if capitalize else character)
        capitalize = character in " _-"
    return "".join(result)


def plain_markdown(text):
    """Keep Markdown structure readable without terminal styling escapes."""
    text = sanitize(text).replace("\r", "")
    lines = []
    in_code = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            while stripped.startswith("#"):
                stripped = stripped[1:].lstrip()
            if stripped.startswith(">"):
                stripped = "> " + stripped[1:].lstrip()
            line = stripped if stripped != "" else ""
        lines.append(line)
    return "\n".join(lines)


def wrap_text(text, width):
    if width < 1:
        return []
    output = []
    for paragraph in plain_markdown(text).split("\n"):
        if paragraph == "":
            output.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            if not word:
                continue
            while len(word) > width:
                if current:
                    output.append(current)
                    current = ""
                output.append(word[:width])
                word = word[width:]
            candidate = word if not current else current + " " + word
            if len(candidate) <= width:
                current = candidate
            else:
                output.append(current)
                current = word
        if current or not output:
            output.append(current)
    return output


def decode_art(value):
    if not isinstance(value, str):
        return "[invalid art]"
    try:
        padding = "=" * ((4 - len(value) % 4) % 4)
        return sanitize(binascii.a2b_base64(value + padding).decode("utf-8"))
    except (ValueError, TypeError, UnicodeError):
        return "[invalid art]"


def style_names(message):
    style = message.get("style")
    if isinstance(style, list):
        return [str(value) for value in style]
    if style:
        return [str(style)]
    return []


def attachment_urls(item):
    result = []
    attachments = item.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            url = attachment.get("url") or attachment.get("src")
            if url:
                result.append((attachment.get("type") or "attachment", str(url)))
    for key, label in (("imageUrl", "image"), ("gifUrl", "GIF"),
                       ("websiteUrl", "website")):
        if item.get(key):
            result.append((label, str(item[key])))
    audio = item.get("audioAttachment")
    if isinstance(audio, dict) and audio.get("src"):
        result.append(("audio", str(audio["src"])))
    unique = []
    seen = set()
    for label, url in result:
        if url not in seen:
            unique.append((label, sanitize(url)))
            seen.add(url)
    return unique


def render_message(message, reveal_spoiler=False):
    if message.get("deleted"):
        return "[deleted message]"
    styles = style_names(message)
    content = message.get("content") or ""
    if "art" in styles:
        content = decode_art(content)
    elif "spoiler" in styles and not reveal_spoiler:
        content = "[spoiler hidden - press v to reveal]"
    else:
        content = plain_markdown(content)
    username = sanitize(message.get("username") or message.get("senderUsername") or "?")
    if message.get("isAction"):
        prefix = "* " + username + " "
    else:
        prefix = username + ": "
    visible_styles = [value for value in styles if value not in ("art", "spoiler")]
    if visible_styles:
        prefix += "[{}] ".format("+".join(visible_styles))
    lines = [prefix + content]
    content_url = content.strip()
    for label, url in attachment_urls(message):
        if url != content_url:
            lines.append("[{}] {}".format(label, url))
    return "\n".join(lines)

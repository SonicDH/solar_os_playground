#!/usr/bin/env python3
"""Build a SolarOS Wikipedia offline library on a desktop computer."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


USER_AGENT = "SolarOS-Wikipedia-Offline-Builder/0.1"


def stable_id(value: str) -> str:
    first = 0x1357
    second = 0x2468
    for character in value:
        code = ord(character)
        first = ((first * 33) + code) & 0xFFFF
        second = ((second * 131) ^ code) & 0xFFFF
    return f"{first:04x}{second:04x}"


def device_key(title: str) -> str:
    return urllib.parse.quote(title.replace(" ", "_"), safe="-._~")


def clean_space(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def wrap(value: str, width: int) -> list[str]:
    lines: list[str] = []
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


def formatted_body(extract: str, width: int) -> str:
    output: list[str] = []
    for paragraph in extract.replace("\r", "").split("\n"):
        paragraph = clean_space(paragraph)
        if paragraph.startswith("==") and paragraph.endswith("=="):
            paragraph = "## " + paragraph.strip("= ")
        if paragraph:
            output.extend(wrap(paragraph, width))
        output.append("")
    return "\n".join(output) + "\n"


def parse_wikipedia_url(value: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(value.strip())
    host = parsed.hostname or ""
    if not host.endswith(".wikipedia.org"):
        raise ValueError("not a wikipedia.org URL")
    language = host[: -len(".wikipedia.org")]
    marker = "/wiki/"
    if not parsed.path.startswith(marker):
        raise ValueError("expected a /wiki/ article URL")
    title = urllib.parse.unquote(parsed.path[len(marker):]).replace("_", " ")
    if not title:
        raise ValueError("article title is missing")
    return language, title


def read_input(path: Path) -> list[tuple[str, str]]:
    articles: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        try:
            article = parse_wikipedia_url(value)
        except ValueError as error:
            raise ValueError(f"{path}:{number}: {error}: {value}") from error
        if article not in seen:
            seen.add(article)
            articles.append(article)
    return articles


def fetch_article(language: str, title: str, timeout: float) -> tuple[str, str, list[str]]:
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "prop": "extracts|links",
            "explaintext": "1",
            "exsectionformat": "plain",
            "plnamespace": "0",
            "pllimit": "200",
            "redirects": "1",
            "titles": title,
            "format": "xml",
        }
    )
    url = f"https://{language}.wikipedia.org/w/api.php?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/xml"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    root = ET.fromstring(payload)
    page = root.find(".//page")
    if page is None or page.get("missing") is not None:
        raise RuntimeError("article was not found")
    canonical_title = page.get("title") or title
    extract_node = page.find("extract")
    extract = extract_node.text if extract_node is not None and extract_node.text else ""
    links: list[str] = []
    seen: set[str] = set()
    for node in page.findall(".//pl"):
        link_title = node.get("title", "")
        if link_title and ":" not in link_title and link_title not in seen:
            seen.add(link_title)
            links.append(link_title)
    return canonical_title, extract, links


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_offline(path: Path) -> list[dict[str, str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return [item for item in value.get("items", []) if isinstance(item, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def write_article(output: Path, language: str, title: str, extract: str,
                  links: list[str], width: int) -> dict[str, str]:
    key = device_key(title)
    directory = output / "cache" / ("v4-" + stable_id(language + "\n" + key))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "body.txt").write_text(formatted_body(extract, width), encoding="utf-8")
    with (directory / "links.jsonl").open("w", encoding="utf-8", newline="\n") as target:
        for number, link_title in enumerate(links, 1):
            record = {
                "id": number,
                "key": device_key(link_title),
                "title": link_title,
            }
            target.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {"key": key, "title": title, "language": language}


def build(args: argparse.Namespace) -> int:
    articles = read_input(args.input)
    if not articles:
        print("No Wikipedia links found in the input file.", file=sys.stderr)
        return 2
    languages = {language for language, _ in articles}
    if len(languages) != 1:
        joined = ", ".join(sorted(languages))
        print(f"Mixed Wikipedia languages are not supported in one device library: {joined}", file=sys.stderr)
        return 2
    language = next(iter(languages))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "cache").mkdir(exist_ok=True)
    offline_path = args.output / "offline.json"
    offline = load_offline(offline_path)
    failures = 0
    for index, (_, requested_title) in enumerate(articles, 1):
        print(f"[{index}/{len(articles)}] {requested_title}")
        try:
            title, extract, links = fetch_article(language, requested_title, args.timeout)
            record = write_article(args.output, language, title, extract,
                                   links, args.width)
            offline = [item for item in offline
                       if not (item.get("key") == record["key"] and
                               item.get("language", language) == language)]
            offline.append(record)
            atomic_json(offline_path, {"items": offline})
            print(f"  saved {len(extract):,} characters and {len(links)} links")
        except (OSError, RuntimeError, ET.ParseError, urllib.error.URLError) as error:
            failures += 1
            print(f"  ERROR: {error}", file=sys.stderr)
        if index < len(articles) and args.delay:
            time.sleep(args.delay)
    atomic_json(args.output / "config.json", {"language": language})
    print(f"\nOutput: {args.output.resolve()}")
    print("Copy cache/, offline.json, and config.json into /apps/wikipedia on SolarOS.")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a SolarOS Wikipedia offline cache from a file of article URLs."
    )
    parser.add_argument("input", type=Path, help="UTF-8 file containing one Wikipedia URL per line")
    parser.add_argument("-o", "--output", type=Path, default=Path("wikipedia-offline"),
                        help="output app-data directory (default: wikipedia-offline)")
    parser.add_argument("--width", type=int, default=48,
                        help="article text width in characters (default: 48)")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="HTTP timeout per article in seconds (default: 30)")
    parser.add_argument("--delay", type=float, default=0.2,
                        help="delay between API requests in seconds (default: 0.2)")
    args = parser.parse_args()
    if args.width < 20:
        parser.error("--width must be at least 20")
    try:
        return build(args)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

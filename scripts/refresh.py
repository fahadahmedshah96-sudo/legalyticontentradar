#!/usr/bin/env python3
"""Refresh seeded public competitor pages and discover company announcements.

Stores only page metadata/headings and a SHA-256 fingerprint, not full page text.
This is a low-frequency research aid, not a legal-content verifier.
"""
from __future__ import annotations
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
UA = "LegalytiContentRadar/0.1 (public content metadata monitor)"
TIMEOUT = 20
DELAY = 1.2


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.published = ""
        self.modified = ""
        self.headings: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._tag = ""
        self._capture = ""
        self._buf: list[str] = []
        self._anchor: list[str] = []
        self._anchor_href = ""

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "meta":
            name = (attr.get("name") or attr.get("property") or "").lower()
            content = html.unescape(attr.get("content", "")).strip()
            if name in {"description", "og:description"} and not self.description:
                self.description = content
            elif name in {"article:published_time", "datepublished", "date"} and not self.published:
                self.published = content
            elif name in {"article:modified_time", "datemodified"} and not self.modified:
                self.modified = content
        if tag == "title" or re.fullmatch(r"h[1-3]", tag or ""):
            self._tag = tag
            self._capture = tag
            self._buf = []
        if tag == "a":
            self._anchor_href = attr.get("href", "")
            self._anchor = []

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self._capture:
            self._buf.append(value)
        if self._anchor_href:
            self._anchor.append(value)

    def handle_endtag(self, tag):
        if tag == self._capture and self._buf:
            value = " ".join(self._buf).strip()
            if tag == "title":
                self.title = value
            elif re.fullmatch(r"h[1-3]", tag):
                self.headings.append(value)
            self._capture = ""
            self._buf = []
        if tag == "a" and self._anchor_href:
            label = " ".join(self._anchor).strip()
            if self._anchor_href and label:
                self.links.append((self._anchor_href, label))
            self._anchor_href = ""
            self._anchor = []


def load_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def save_json(name, data):
    path = DATA / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def can_fetch(url: str) -> tuple[bool, str]:
    parts = urllib.parse.urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        request = urllib.request.Request(robots_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            robots_body = resp.read(250_000).decode("utf-8", "replace")
        parser.parse(robots_body.splitlines())
        allowed = parser.can_fetch(UA, url)
        return allowed, "robots.txt allows this path" if allowed else "Disallowed by robots.txt"
    except Exception as exc:
        # If robots.txt cannot be retrieved, fail closed for this run and let a human check.
        return False, f"Could not confirm robots.txt permission: {type(exc).__name__}"


def get_page(url: str) -> tuple[int | None, str, dict]:
    allowed, note = can_fetch(url)
    if not allowed:
        return None, note, {}
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(2_000_000).decode(resp.headers.get_content_charset() or "utf-8", "replace")
            parser = PageParser()
            parser.feed(body)
            metadata = {
                "title": parser.title,
                "description": parser.description,
                "published_date": parser.published,
                "modified_date": parser.modified,
                "headings": parser.headings[:35],
                "links": parser.links[:500],
                "final_url": resp.geturl(),
                "etag": resp.headers.get("ETag"),
                "last_modified_header": resp.headers.get("Last-Modified"),
            }
            return resp.status, body, metadata
    except urllib.error.HTTPError as exc:
        return exc.code, "", {"error": f"HTTP {exc.code}"}
    except Exception as exc:
        return None, "", {"error": f"{type(exc).__name__}: {exc}"}


def fingerprint(metadata: dict) -> str:
    material = "\n".join([
        metadata.get("title", ""), metadata.get("description", ""),
        metadata.get("published_date", ""), metadata.get("modified_date", ""),
        *metadata.get("headings", []),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def absolute_url(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(href)).split("#", 1)[0]


def refresh_content() -> int:
    rows = load_json("competitor_content.json")
    timestamp = now_iso()
    updated = 0
    for row in rows:
        code, body, meta = get_page(row["url"])
        row["last_checked"] = timestamp
        row["http_status"] = code
        if code and 200 <= code < 300 and meta.get("title"):
            digest = fingerprint(meta)
            old = row.get("content_hash")
            row["live_title"] = meta.get("title")
            row["live_description"] = meta.get("description")
            row["live_headings"] = meta.get("headings", [])
            row["live_published_date"] = meta.get("published_date") or None
            row["live_modified_date"] = meta.get("modified_date") or None
            row["final_url"] = meta.get("final_url")
            row["content_hash"] = digest
            row["change_status"] = "baseline_created" if not old else ("changed" if old != digest else "unchanged")
            row.pop("fetch_error", None)
        else:
            row["change_status"] = "fetch_blocked_or_failed"
            row["fetch_error"] = meta.get("error") or body or "Robots permission could not be confirmed."
        updated += 1
        time.sleep(DELAY)
    save_json("competitor_content.json", rows)
    return updated


def refresh_news_listing() -> int:
    sources = load_json("news_sources.json")
    items = load_json("competitor_news.json")
    known = {item.get("url") for item in items}
    timestamp = now_iso()
    discovered = []
    for source in sources:
        code, body, meta = get_page(source["source_url"])
        source["last_checked"] = timestamp
        source["http_status"] = code
        if not (code and 200 <= code < 300):
            source["last_error"] = meta.get("error") or "Fetch unavailable or blocked by robots.txt"
            continue
        source.pop("last_error", None)
        parser = PageParser()
        try:
            parser.feed(body)
        except Exception:
            continue
        required = source.get("include_path", "")
        base_host = urllib.parse.urlsplit(source["source_url"]).netloc
        for href, label in parser.links:
            url = absolute_url(source["source_url"], href)
            parts = urllib.parse.urlsplit(url)
            if parts.netloc != base_host or not required or required not in parts.path or url in known:
                continue
            if len(label) < 10 or len(label) > 180:
                continue
            discovered.append({
                "id": hashlib.md5(url.encode()).hexdigest()[:16],
                "competitor": source["competitor"],
                "url": url,
                "title": label,
                "published_date": None,
                "news_type": "Needs classification",
                "summary": "New item found on a configured competitor press listing. Review the linked page before classifying.",
                "why_it_matters": "AI or human analysis pending; do not treat this row as a validated competitive claim.",
                "source_type": "Discovered listing link",
                "source_date": timestamp[:10],
                "location": "Configured public source",
                "last_checked": timestamp,
                "change_status": "new_discovery"
            })
            known.add(url)
        time.sleep(DELAY)
    items = discovered + items
    items.sort(key=lambda x: x.get("published_date") or x.get("source_date") or "", reverse=True)
    save_json("competitor_news.json", items)
    save_json("news_sources.json", sources)
    return len(discovered)


if __name__ == "__main__":
    try:
        page_count = refresh_content()
        news_count = refresh_news_listing()
        print(f"Checked {page_count} seeded competitor pages; discovered {news_count} press-listing links.")
    except Exception as exc:
        print(f"Refresh failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise

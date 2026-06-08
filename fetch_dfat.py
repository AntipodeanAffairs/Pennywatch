"""DFAT/foreignminister.gov.au scraper — RSS-only second source.

v1.5.3 (RSS) — Earlier versions (v1.5.0–v1.5.2) scraped the listing+detail
pages, but foreignminister.gov.au's WAF silently blocks GitHub Actions
runner IP ranges. The site's public RSS feed at /rss.xml is served from
a cached endpoint that is NOT WAF-protected, and (we discovered)
contains the FULL HTML body of each release in the <description> field —
not a short summary. So RSS-only gives us the same classifier signal as
the full-page scrape, with the only sacrifice being no historical
backfill: the feed only ever contains the latest 10 items.

Each daily run picks up everything that has appeared since the previous
run, and the incremental-merge logic in build_tracker.py preserves all
prior records. So the dataset grows forward from the day v1.5.3 lands.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RSS_URL = "https://www.foreignminister.gov.au/rss.xml"

# Use a Firefox-shaped UA with a PennyWatch identifier appended — the
# /rss.xml endpoint isn't WAF-protected, but being polite costs nothing.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0 "
    "PennyWatch/1.0"
)

# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def _http_get(url: str, retries: int = 4) -> str | None:
    """GET a URL with exponential-backoff retry on transient failures."""
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml,text/xml,*/*"})
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=30) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except HTTPError as e:
            if e.code == 404:
                return None
            if 500 <= e.code < 600 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            print(f"  DFAT fetch {url} HTTP {e.code}", file=sys.stderr)
            return None
        except (URLError, RemoteDisconnected, TimeoutError, OSError) as e:
            if attempt < retries - 1:
                print(f"  DFAT fetch {url} transient ({type(e).__name__}); retry {attempt + 1}",
                      file=sys.stderr)
                time.sleep(2 ** attempt)
                continue
            print(f"  DFAT fetch {url} failed: {e}", file=sys.stderr)
            return None
    return None


# --------------------------------------------------------------------------- #
# RSS parsing
# --------------------------------------------------------------------------- #

_ITEM_RX = re.compile(r"<item>(.*?)</item>", re.DOTALL)
_TITLE_RX = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_LINK_RX = re.compile(r"<link>(.*?)</link>", re.DOTALL)
_PUBDATE_RX = re.compile(r"<pubDate>(.*?)</pubDate>", re.DOTALL)
_DESC_RX = re.compile(r"<description>(.*?)</description>", re.DOTALL)
_TAG_STRIP_RX = re.compile(r"<[^>]+>")
_WS_RX = re.compile(r"\s+")


def _decode_entities(s: str) -> str:
    """Replace HTML entities common in RSS-wrapped HTML."""
    for ent, ch in (
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&apos;", "'"), ("&#039;", "'"),
        ("&nbsp;", " "),
        ("&rsquo;", "'"), ("&lsquo;", "'"),
        ("&rdquo;", '"'), ("&ldquo;", '"'),
        ("&mdash;", "—"), ("&ndash;", "–"), ("&hellip;", "…"),
    ):
        s = s.replace(ent, ch)
    return s


def _clean_html_text(html_frag: str) -> str:
    """Strip HTML tags, decode entities, normalise whitespace, preserve
    paragraph breaks (which matter for sentence-level classifier scoping)."""
    # First decode entities so the inner HTML reveals itself
    s = _decode_entities(html_frag)
    # Insert newlines around block-level tags before stripping them
    s = re.sub(r"</?(p|br|div|li|h\d|blockquote)[^>]*>", "\n", s, flags=re.IGNORECASE)
    # Strip remaining tags
    s = _TAG_STRIP_RX.sub("", s)
    # Decode again in case we revealed double-encoded entities
    s = _decode_entities(s)
    # Normalise whitespace; preserve paragraph boundaries
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{2,}", "\n\n", s)
    return s.strip()


def _slug_from_link(link: str) -> str:
    return link.rstrip("/").rsplit("/", 1)[-1]


def _detect_joint_with(text: str) -> list[str]:
    """Best-effort detection of joint-statement co-signers from the body
    text. The RSS feed loses the structured "Joint statement with: …" block
    from the detail page, but co-signers can usually be inferred from
    "Quotes attributable to <Title> <Name>:" blocks that bracket the body.
    We collect any names that match that pattern. Not 100% reliable; the
    methodology calls this out."""
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"Quotes? attributable to\s+([^:\n]{3,120}):", text):
        name = m.group(1).strip().rstrip(".,;")
        # Skip if the captured name is just Wong herself (the speaker)
        if "Penny Wong" in name and "and" not in name.lower():
            continue
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _parse_pubdate(pubdate_str: str) -> str | None:
    """Convert an RSS pubDate (RFC 2822-ish) to ISO 8601 UTC."""
    try:
        dt = parsedate_to_datetime(pubdate_str.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def fetch_dfat_releases(since: str, max_pages: int | None = None) -> list[dict]:
    """Fetch Penny Wong's media releases from the official RSS feed.

    Returns records with: id, url, source, created_at, title, text, joint_with.
    The `since` parameter filters out items older than that ISO 8601 date.
    The `max_pages` parameter is accepted for API compatibility with the
    legacy listing-based fetcher but is ignored (RSS is a single document).
    """
    try:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        since_dt = datetime(2022, 6, 1, tzinfo=timezone.utc)

    print(f"Fetching DFAT RSS feed ({RSS_URL})", file=sys.stderr)
    xml = _http_get(RSS_URL)
    if not xml:
        print("DFAT RSS feed unfetchable; returning empty", file=sys.stderr)
        return []

    items = _ITEM_RX.findall(xml)
    print(f"DFAT RSS contains {len(items)} items", file=sys.stderr)

    out: list[dict] = []
    skipped_old = 0

    for raw in items:
        title_m = _TITLE_RX.search(raw)
        link_m = _LINK_RX.search(raw)
        pub_m = _PUBDATE_RX.search(raw)
        desc_m = _DESC_RX.search(raw)

        if not (title_m and link_m and pub_m and desc_m):
            continue

        title = _clean_html_text(title_m.group(1))
        link = _decode_entities(link_m.group(1).strip())
        created_at = _parse_pubdate(pub_m.group(1))
        body = _clean_html_text(desc_m.group(1))

        if not created_at or not body:
            continue
        try:
            item_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if item_dt < since_dt:
            skipped_old += 1
            continue

        slug = _slug_from_link(link)
        joint = _detect_joint_with(body)

        out.append({
            "id": f"dfat:{slug}",
            "url": link,
            "source": "dfat",
            "created_at": created_at,
            "title": title,
            # Prepend title to body so classifier picks up triggers in the
            # headline (which is often the most punchy critical/positive phrase).
            "text": f"{title}. {body}",
            "joint_with": joint,
        })

    if skipped_old:
        print(f"DFAT RSS: skipped {skipped_old} items older than {since}", file=sys.stderr)
    print(f"DFAT RSS: returning {len(out)} releases", file=sys.stderr)
    return out


if __name__ == "__main__":
    # CLI smoke test: fetch the current RSS feed back to 2022-06-01 and
    # print a summary of each release we'd add.
    import json
    releases = fetch_dfat_releases("2022-06-01T00:00:00Z")
    for r in releases:
        print(f"  {r['created_at'][:10]}  {r['title'][:70]}")
        if r["joint_with"]:
            print(f"    joint_with: {r['joint_with']}")
        print(f"    body: {r['text'][:140]}…")
        print()
    print(f"Total: {len(releases)}")

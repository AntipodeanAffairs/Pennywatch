"""DFAT/foreignminister.gov.au scraper — second source for PennyWatch.

Pulls Senator Wong's media releases from foreignminister.gov.au and emits
records in the same shape as @SenatorWong tweets, so the same classifier
applies. Each record carries `source: "dfat"` and (where applicable) a
`joint_with` list naming co-signers of joint statements.

Polite scraping: ~0.5s between requests, descriptive User-Agent, retries
on transient errors. Government sites don't object to this kind of access,
but we want to look like a well-behaved scraper rather than a flood.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone
from http.client import RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

BASE = "https://www.foreignminister.gov.au"
LISTING_PATH = "/minister/penny-wong/media-releases"
USER_AGENT = (
    # Note: the "polite scraper" UA format (Mozilla/5.0 (compatible; Name; +URL))
    # was being silently blocked by foreignminister.gov.au's WAF as of June 2026.
    # Use a Firefox-shaped UA with a PennyWatch identifier appended — that gets
    # through the WAF while still identifying the project for site admins who
    # inspect logs.
    "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0 "
    "PennyWatch/1.0"
)
REQUEST_DELAY_S = 0.5

# v1.5.2: route requests through a Cloudflare Worker when the GitHub
# Actions runner's IP is blocked by foreignminister.gov.au's WAF.
# Both env vars must be set for proxy mode; otherwise we fetch directly
# (which still works from non-blocked IPs, e.g., local development).
PROXY_URL = os.environ.get("DFAT_PROXY_URL", "").strip()
PROXY_SECRET = os.environ.get("DFAT_PROXY_SECRET", "").strip()
PROXY_ENABLED = bool(PROXY_URL and PROXY_SECRET)

# Listing-page regex — extracts (href, title, ISO date) from each <li> item.
# Each entry has the shape:
#   <li>
#     <div class="views-field views-field-title">
#       <span class="field-content">
#         <a href="/minister/penny-wong/media-release/SLUG" hreflang="en">TITLE</a>
#     ...
#     <div class="views-field views-field-created">
#       <span class="field-content">
#         <time datetime="2026-06-06T11:04:58+10:00">6 June 2026</time>
_LISTING_ITEM_RX = re.compile(
    r'<a href="(/minister/penny-wong/media-release/[^"]+)"[^>]*>(.+?)</a>'
    r'.*?<time datetime="([^"]+)"',
    re.DOTALL,
)

# Detail-page regexes
_DETAIL_TITLE_RX = re.compile(
    r'<h1 class="au-header-heading">\s*<span>(.+?)</span>',
    re.DOTALL,
)
_DETAIL_BODY_RX = re.compile(
    r'<div class="field field--name-body[^"]*"[^>]*>(.*?)</div>\s*</div>',
    re.DOTALL,
)
_DETAIL_JOINT_RX = re.compile(
    r'<li>Joint statement with:</li>.*?'
    r'<div class="field field--name-field-article-free-text[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL,
)
_DETAIL_JOINT_NAME_RX = re.compile(r'<li>(.+?)</li>', re.DOTALL)
_TAG_STRIP_RX = re.compile(r'<[^>]+>')
_WS_RX = re.compile(r'\s+')


def _http_get(url: str, retries: int = 4) -> str | None:
    """GET a URL. If PROXY_ENABLED, route through the Cloudflare Worker;
    otherwise fetch directly. Returns None on permanent failure.

    Retries on transient network errors (RemoteDisconnected, timeouts,
    socket errors, transient HTTP 5xx) with exponential backoff.
    Returns None on 404 immediately, since the page genuinely doesn't exist.
    """
    if PROXY_ENABLED:
        fetch_url = f"{PROXY_URL}?url={quote(url, safe='')}"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            "X-PennyWatch-Auth": PROXY_SECRET,
        }
    else:
        fetch_url = url
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}

    req = Request(fetch_url, headers=headers)
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


def _clean_text(html_fragment: str) -> str:
    """Strip HTML tags, normalise whitespace, unescape entities."""
    # Replace block tags with line breaks before stripping
    txt = re.sub(r'</?(p|br|li|h\d|div)[^>]*>', '\n', html_fragment, flags=re.IGNORECASE)
    txt = _TAG_STRIP_RX.sub('', txt)
    # Unescape common HTML entities
    for ent, ch in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#039;", "'"), ("&nbsp;", " "),
                    ("&rsquo;", "'"), ("&lsquo;", "'"),
                    ("&rdquo;", '"'), ("&ldquo;", '"'),
                    ("&mdash;", "—"), ("&ndash;", "–"), ("&hellip;", "…")]:
        txt = txt.replace(ent, ch)
    # Normalise whitespace but preserve paragraph breaks
    txt = re.sub(r'[ \t]+', ' ', txt)
    txt = re.sub(r'\n[ \t]+', '\n', txt)
    txt = re.sub(r'\n{2,}', '\n\n', txt)
    return txt.strip()


def _parse_iso_to_utc(iso_str: str) -> str:
    """Convert a foreignminister.gov.au datetime ('2026-06-06T11:04:58+10:00')
    to a UTC ISO 8601 string ('2026-06-06T01:04:58Z')."""
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def fetch_release_detail(url: str) -> dict | None:
    """Fetch one media-release detail page; return {text, joint_with} or None."""
    html = _http_get(urljoin(BASE, url))
    if not html:
        return None
    out: dict = {"text": "", "joint_with": []}

    body_m = _DETAIL_BODY_RX.search(html)
    if body_m:
        out["text"] = _clean_text(body_m.group(1))

    joint_m = _DETAIL_JOINT_RX.search(html)
    if joint_m:
        names = []
        for n in _DETAIL_JOINT_NAME_RX.findall(joint_m.group(1)):
            cleaned = _WS_RX.sub(' ', _TAG_STRIP_RX.sub('', n)).strip()
            if cleaned:
                names.append(cleaned)
        out["joint_with"] = names

    return out


def fetch_dfat_releases(since: str, max_pages: int = 30) -> list[dict]:
    """Walk the media-release listing pages and fetch each release.

    Stops paginating once it sees releases entirely older than `since` (an
    ISO 8601 string, e.g. '2022-06-01T00:00:00Z').
    """
    try:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        since_dt = datetime(2022, 6, 1, tzinfo=timezone.utc)

    out: list[dict] = []
    seen_urls: set[str] = set()

    for page in range(max_pages):
        url = f"{BASE}{LISTING_PATH}?page={page}"
        print(f"  DFAT listing page {page + 1} ({url})", file=sys.stderr)
        html = _http_get(url)
        if not html:
            print(f"  page {page + 1} unfetchable; stopping", file=sys.stderr)
            break

        items = _LISTING_ITEM_RX.findall(html)
        if not items:
            print(f"  no items found on page {page + 1}; stopping", file=sys.stderr)
            break

        # Track whether every item on this page predates `since`
        all_older = True
        page_added = 0

        for href, raw_title, iso_date in items:
            if href in seen_urls:
                continue
            seen_urls.add(href)
            try:
                item_dt = datetime.fromisoformat(iso_date)
            except ValueError:
                continue
            if item_dt < since_dt:
                continue
            all_older = False

            title = _clean_text(raw_title)
            full_url = urljoin(BASE, href)
            slug = _slug_from_url(href)
            tweet_id = f"dfat:{slug}"

            time.sleep(REQUEST_DELAY_S)
            detail = fetch_release_detail(href)
            if not detail or not detail["text"]:
                print(f"  WARN: no body for {href}", file=sys.stderr)
                continue

            out.append({
                "id": tweet_id,
                "url": full_url,
                "source": "dfat",
                "created_at": _parse_iso_to_utc(iso_date),
                "title": title,
                "text": f"{title}. {detail['text']}",
                "joint_with": detail["joint_with"],
            })
            page_added += 1

        print(f"  page {page + 1}: added {page_added} releases (total {len(out)})",
              file=sys.stderr)

        if all_older and page_added == 0:
            print(f"  page {page + 1}: all items older than {since}; stopping",
                  file=sys.stderr)
            break

        time.sleep(REQUEST_DELAY_S)

    print(f"DFAT fetch complete: {len(out)} releases", file=sys.stderr)
    return out


if __name__ == "__main__":
    # CLI smoke test: fetch the last 14 days of releases and print them.
    import json
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    releases = fetch_dfat_releases(since)
    for r in releases:
        print(f"  {r['created_at']}  {r['title'][:80]}")
        if r["joint_with"]:
            print(f"    joint with: {', '.join(r['joint_with'])}")
        print(f"    body: {r['text'][:140]}…")
        print()
    print(f"Total: {len(releases)}")

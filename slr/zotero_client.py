#!/usr/bin/env python3
"""
zotero_client.py

Purpose : CLI wrapper for common Zotero API operations needed during the SLR.
          Reads credentials from slr/.env (or environment variables directly).
Inputs  : subcommand + flags (see --help for each subcommand)
Outputs : JSON to stdout; errors to stderr
Deps    : requests (pip install requests), python-dotenv (pip install python-dotenv)

Usage examples:
  python zotero_client.py list-collections
  python zotero_client.py search --query "generative AI metadata extraction" --limit 25
  python zotero_client.py get-item --key ABC123XY
  python zotero_client.py add-tag --key ABC123XY --tag "included-phase1"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Load .env from the slr/ directory (one level up from scripts/)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass  # Fall through to raw os.environ; warn below if keys missing

try:
    import requests
except ImportError:
    sys.exit("Error: 'requests' package not installed. Run: pip install requests")


def _get_env(key: str, required: bool = True) -> str:
    val = os.environ.get(key, "")
    if required and not val:
        sys.exit(f"Error: {key} is not set. Copy slr/.env.example to slr/.env and fill in your keys.")
    return val


def _build_base_url() -> str:
    base = _get_env("ZOTERO_API_BASE_URL", required=False) or "https://api.zotero.org"
    lib_type = _get_env("ZOTERO_LIBRARY_TYPE", required=False) or "group"
    if lib_type == "group":
        lib_id = _get_env("ZOTERO_GROUP_ID")
        return f"{base}/groups/{lib_id}"
    else:
        lib_id = _get_env("ZOTERO_USER_ID")
        return f"{base}/users/{lib_id}"


def _session(write: bool = False) -> requests.Session:
    s = requests.Session()
    key_env = "ZOTERO_API_KEY_READWRITE" if write else "ZOTERO_API_KEY_READONLY"
    api_key = _get_env(key_env)
    s.headers.update({
        "Zotero-API-Key": api_key,
        "Zotero-API-Version": "3",
        "Content-Type": "application/json",
    })
    return s


def cmd_list_collections(args: argparse.Namespace) -> None:
    base = _build_base_url()
    r = _session().get(f"{base}/collections", params={"limit": args.limit})
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    base = _build_base_url()
    params: dict = {"q": args.query, "limit": args.limit}
    if args.collection:
        params["collectionKey"] = args.collection
    if args.tag:
        params["tag"] = args.tag
    r = _session().get(f"{base}/items", params=params)
    r.raise_for_status()
    items = r.json()
    if args.brief:
        brief = [
            {
                "key": i["key"],
                "title": i["data"].get("title", ""),
                "year": i["data"].get("date", "")[:4],
                "type": i["data"].get("itemType", ""),
            }
            for i in items
        ]
        print(json.dumps(brief, indent=2))
    else:
        print(json.dumps(items, indent=2))


def cmd_get_item(args: argparse.Namespace) -> None:
    base = _build_base_url()
    r = _session().get(f"{base}/items/{args.key}")
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


def cmd_add_tag(args: argparse.Namespace) -> None:
    base = _build_base_url()
    sess = _session(write=True)
    # Fetch current item to get version and existing tags
    r = sess.get(f"{base}/items/{args.key}")
    r.raise_for_status()
    item = r.json()
    version = item["version"]
    data = item["data"]
    existing_tags = data.get("tags", [])
    new_tag = {"tag": args.tag}
    if new_tag not in existing_tags:
        existing_tags.append(new_tag)
    patch = {"tags": existing_tags}
    resp = sess.patch(
        f"{base}/items/{args.key}",
        json=patch,
        headers={"If-Unmodified-Since-Version": str(version)},
    )
    resp.raise_for_status()
    print(json.dumps({"key": args.key, "tag_added": args.tag, "status": resp.status_code}))


def cmd_list_items(args: argparse.Namespace) -> None:
    base = _build_base_url()
    params: dict = {"limit": args.limit, "start": args.start}
    if args.collection:
        url = f"{base}/collections/{args.collection}/items"
    else:
        url = f"{base}/items"
    if args.tag:
        params["tag"] = args.tag
    r = _session().get(url, params=params)
    r.raise_for_status()
    total = r.headers.get("Total-Results", "?")
    items = r.json()
    if args.brief:
        brief = [
            {
                "key": i["key"],
                "title": i["data"].get("title", ""),
                "year": i["data"].get("date", "")[:4],
                "type": i["data"].get("itemType", ""),
                "tags": [t["tag"] for t in i["data"].get("tags", [])],
            }
            for i in items
        ]
        print(f"# Total in library: {total}")
        print(json.dumps(brief, indent=2))
    else:
        print(json.dumps(items, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Zotero API client for the GenAI Archival Metadata SLR"
    )
    sub = p.add_subparsers(dest="command", required=True)

    # list-collections
    lc = sub.add_parser("list-collections", help="List library collections")
    lc.add_argument("--limit", type=int, default=50)
    lc.set_defaults(func=cmd_list_collections)

    # search
    s = sub.add_parser("search", help="Full-text search across library items")
    s.add_argument("--query", "-q", required=True)
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--collection", help="Restrict to collection key")
    s.add_argument("--tag", help="Filter by tag")
    s.add_argument("--brief", action="store_true", help="Return key/title/year/type only")
    s.set_defaults(func=cmd_search)

    # get-item
    gi = sub.add_parser("get-item", help="Retrieve a single item by key")
    gi.add_argument("--key", required=True)
    gi.set_defaults(func=cmd_get_item)

    # add-tag
    at = sub.add_parser("add-tag", help="Append a tag to an item (uses read-write key)")
    at.add_argument("--key", required=True, help="Zotero item key")
    at.add_argument("--tag", required=True, help="Tag string to add")
    at.set_defaults(func=cmd_add_tag)

    # list-items
    li = sub.add_parser("list-items", help="List items, optionally filtered by collection or tag")
    li.add_argument("--collection", help="Collection key (omit for whole library)")
    li.add_argument("--tag", help="Filter by tag")
    li.add_argument("--limit", type=int, default=50)
    li.add_argument("--start", type=int, default=0, help="Pagination offset")
    li.add_argument("--brief", action="store_true")
    li.set_defaults(func=cmd_list_items)

    return p


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)

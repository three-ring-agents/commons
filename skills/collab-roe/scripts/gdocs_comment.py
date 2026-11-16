#!/usr/bin/env python3
"""Native Google Docs API v1 anchored comment helper, batch generator & transparent gdocs shim.

Bypasses the `errAnchoredCommentsUnavailable` stub in `gdocs-986250228` by calling
`POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate` with
`InsertCommentRequest` (`insertComment`), `AddCommentReplyRequest` (`addCommentReply`),
or `DeleteCommentRequest` (`deleteComment`).

Supports:
  - `add-comment` / `add` (and transparent `gdocs mutate add-comment` shim invocation)
  - `post` (`--doc-id`, `--operator`, `--quote`, `--content` compatibility interface)
  - `reply-comment` / `reply`
  - `delete-comment` / `delete`
  - `make-batch` (`--operator`, `--bullets`, `--out` inline callout JSON generator)

Works identically on:
  - Antigravity Cloud Remote Agent VMs (`jetski` via `GDOCS_TOKEN_FILE`, `/tmp/agy-plugin-tokens-*`, + `agy-plugin-proxy`)
  - Local macOS / Linux hosts (`mac-mini` via `~/.gemini/antigravity/plugin_data/gdocs/token.json`)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _find_token_file() -> Path:
    candidates: List[Path] = []
    if os.environ.get("GDOCS_TOKEN_FILE"):
        candidates.append(Path(os.environ["GDOCS_TOKEN_FILE"]))
    app_data = os.environ.get("ANTIGRAVITY_APP_DATA_DIR")
    if app_data:
        candidates.append(Path(app_data) / "plugin_data" / "gdocs" / "token.json")
    for pat in (
        "/tmp/agy-plugin-tokens-*/gdocs/token.json",
        "/tmp/agy-plugin-tokens-*/gdrive/token.json",
    ):
        for p in sorted(glob.glob(pat)):
            candidates.append(Path(p))
    candidates.append(Path.home() / ".gemini" / "antigravity" / "plugin_data" / "gdocs" / "token.json")
    candidates.append(Path.home() / ".gemini" / "jetski" / "plugin_data" / "gdocs" / "token.json")

    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError(
        "No gdocs OAuth token file found. Run `gdocs auth login` on local machines or reconnect the Google Docs plugin."
    )


def _refresh_via_oauth2(token_path: Path, raw: Dict[str, Any]) -> Optional[str]:
    inner = raw.get("token") if isinstance(raw.get("token"), dict) else raw
    refresh_token = inner.get("refresh_token") or raw.get("refresh_token")
    client_id = (
        inner.get("client_id")
        or raw.get("client_id")
        or "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
    )
    client_secret = inner.get("client_secret") or raw.get("client_secret") or ""
    token_uri = inner.get("token_uri") or raw.get("token_uri") or "https://oauth2.googleapis.com/token"

    if not refresh_token or not client_secret:
        return None

    form = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        token_uri,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            refreshed = json.loads(resp.read().decode("utf-8"))
        new_access = refreshed.get("access_token")
        if new_access:
            if isinstance(raw.get("token"), dict):
                raw["token"]["access_token"] = new_access
            else:
                raw["access_token"] = new_access
            try:
                token_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
            except OSError:
                pass
            return new_access
    except Exception:
        return None
    return None


def _load_access_token(real_binary: Optional[str] = None, doc_id: Optional[str] = None) -> str:
    token_path = _find_token_file()
    raw = json.loads(token_path.read_text(encoding="utf-8"))
    inner = raw.get("token") if isinstance(raw.get("token"), dict) else raw
    access_token = (
        inner.get("access_token")
        or inner.get("accessToken")
        or inner.get("token")
        or raw.get("access_token")
        or raw.get("accessToken")
        or raw.get("token")
    )
    if not access_token:
        raise RuntimeError(f"Could not extract access_token from {token_path}")
    return str(access_token)


def _api_request(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    quota_project: Optional[str] = None,
    real_binary: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> Dict[str, Any]:
    token_path = _find_token_file()
    raw = json.loads(token_path.read_text(encoding="utf-8"))
    token = _load_access_token(real_binary=real_binary, doc_id=doc_id)

    def _do_call(bearer: str) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json",
        }
        if quota_project:
            headers["X-Goog-User-Project"] = quota_project
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    try:
        return _do_call(token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            new_token = _refresh_via_oauth2(token_path, raw)
            if not new_token and real_binary and doc_id and os.path.exists(real_binary):
                subprocess.run(
                    [real_binary, "readonly", "info", doc_id, "--json"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                new_token = _load_access_token()
            if new_token:
                return _do_call(new_token)
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_body)
            msg = err_json.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        raise RuntimeError(f"Google Docs API error (HTTP {e.code}): {msg}") from None


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _flatten_tabs(tabs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in tabs:
        out.append(t)
        child_tabs = t.get("childTabs") or []
        if child_tabs:
            out.extend(_flatten_tabs(child_tabs))
    return out


def _iter_paragraphs(structural_elements: List[Dict[str, Any]]):
    for elem in structural_elements or []:
        if "paragraph" in elem:
            yield elem["paragraph"]
        elif "table" in elem:
            for row in elem["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    yield from _iter_paragraphs(cell.get("content", []))
        elif "tableOfContents" in elem:
            yield from _iter_paragraphs(elem["tableOfContents"].get("content", []))


def _paragraph_text_and_index_map(para: Dict[str, Any]) -> Tuple[str, List[int]]:
    chars: List[str] = []
    indices: List[int] = []
    last_end_utf16: Optional[int] = None

    for el in para.get("elements", []):
        start_idx = el.get("startIndex")
        end_idx = el.get("endIndex")
        if start_idx is None:
            continue
        text_run = el.get("textRun")
        if text_run and "content" in text_run:
            content = text_run["content"]
            cur = start_idx
            for ch in content:
                chars.append(ch)
                indices.append(cur)
                cur += _utf16_len(ch)
            last_end_utf16 = cur
        else:
            span = max(1, (end_idx - start_idx) if end_idx is not None else 1)
            chars.append("\ufffc")
            indices.append(start_idx)
            last_end_utf16 = start_idx + span

    if last_end_utf16 is not None:
        indices.append(last_end_utf16)
    return "".join(chars), indices


def _find_quote_in_body(body: Dict[str, Any], quote: str) -> Optional[Tuple[int, int]]:
    content = body.get("content", [])
    for para in _iter_paragraphs(content):
        text, idx_map = _paragraph_text_and_index_map(para)
        if not text:
            continue
        pos = text.find(quote)
        if pos != -1:
            return idx_map[pos], idx_map[pos + len(quote)]
        q_stripped = quote.strip()
        if q_stripped and q_stripped != quote:
            pos = text.find(q_stripped)
            if pos != -1:
                return idx_map[pos], idx_map[pos + len(q_stripped)]

    q_lower = quote.lower().strip()
    if q_lower:
        for para in _iter_paragraphs(content):
            text, idx_map = _paragraph_text_and_index_map(para)
            pos = text.lower().find(q_lower)
            if pos != -1:
                return idx_map[pos], idx_map[pos + len(q_lower)]

    return None


def _first_nonempty_range_in_body(body: Dict[str, Any]) -> Tuple[int, int]:
    for para in _iter_paragraphs(body.get("content", [])):
        text, idx_map = _paragraph_text_and_index_map(para)
        stripped = text.strip("\n\r\t \ufffc")
        if stripped:
            pos = text.find(stripped)
            return idx_map[pos], idx_map[pos + len(stripped)]
    return 1, 2


def resolve_anchor_range(
    doc: Dict[str, Any],
    quote: Optional[str],
    start: Optional[int],
    end: Optional[int],
    tab_arg: Optional[str],
) -> Tuple[int, int, Optional[str]]:
    tabs = _flatten_tabs(doc.get("tabs") or [])

    target_tabs: List[Dict[str, Any]] = []
    if tabs:
        if tab_arg:
            for t in tabs:
                props = t.get("tabProperties", {})
                if props.get("tabId") == tab_arg or props.get("title") == tab_arg:
                    target_tabs.append(t)
            if not target_tabs:
                avail = [
                    f"{t.get('tabProperties', {}).get('tabId')} ({t.get('tabProperties', {}).get('title')})"
                    for t in tabs
                ]
                raise RuntimeError(f"Tab {tab_arg!r} not found. Available tabs: {', '.join(avail)}")
        else:
            target_tabs = tabs

    if start is not None and end is not None and (start > 0 or end > 0):
        resolved_tab_id = None
        if target_tabs:
            resolved_tab_id = target_tabs[0].get("tabProperties", {}).get("tabId")
        elif tab_arg:
            resolved_tab_id = tab_arg
        return start, end, resolved_tab_id

    if quote:
        if target_tabs:
            for t in target_tabs:
                body = t.get("documentTab", {}).get("body", {})
                found = _find_quote_in_body(body, quote)
                if found:
                    tab_id = t.get("tabProperties", {}).get("tabId")
                    return found[0], found[1], tab_id
            raise RuntimeError(f"Quote {quote!r} not found in document")
        else:
            body = doc.get("body", {})
            found = _find_quote_in_body(body, quote)
            if found:
                return found[0], found[1], None
            raise RuntimeError(f"Quote {quote!r} not found in document")

    if target_tabs:
        first_tab = target_tabs[0]
        body = first_tab.get("documentTab", {}).get("body", {})
        s_idx, e_idx = _first_nonempty_range_in_body(body)
        return s_idx, e_idx, first_tab.get("tabProperties", {}).get("tabId")

    body = doc.get("body", {})
    s_idx, e_idx = _first_nonempty_range_in_body(body)
    return s_idx, e_idx, None


def build_comment_url(doc_id: str, comment_id: str, tab_id: Optional[str] = None) -> str:
    base = f"https://docs.google.com/document/d/{doc_id}/edit"
    params = []
    if tab_id:
        params.append(f"tab={urllib.parse.quote(tab_id)}")
    if comment_id:
        params.append(f"disco={urllib.parse.quote(comment_id)}")
    return f"{base}?{'&'.join(params)}" if params else base


def cmd_add_comment(args: argparse.Namespace, real_binary: Optional[str] = None) -> int:
    doc_id = args.doc_id
    comment_text = args.comment_text
    assignee = getattr(args, "assignee", None) or getattr(args, "assign", None)

    if assignee and assignee not in comment_text:
        comment_text = f"+{assignee} {comment_text}"

    doc_url = f"https://docs.googleapis.com/v1/documents/{urllib.parse.quote(doc_id)}?includeTabsContent=true"
    doc = _api_request("GET", doc_url, quota_project=args.project, real_binary=real_binary, doc_id=doc_id)

    start_idx, end_idx, resolved_tab_id = resolve_anchor_range(
        doc=doc,
        quote=args.quote,
        start=getattr(args, "start", 0),
        end=getattr(args, "end", 0),
        tab_arg=getattr(args, "tab", None),
    )

    range_obj: Dict[str, Any] = {
        "startIndex": start_idx,
        "endIndex": end_idx,
    }
    if resolved_tab_id:
        range_obj["tabId"] = resolved_tab_id

    insert_req: Dict[str, Any] = {
        "range": range_obj,
        "content": comment_text,
    }
    if assignee:
        insert_req["assigneeEmailAddress"] = assignee

    batch_url = f"https://docs.googleapis.com/v1/documents/{urllib.parse.quote(doc_id)}:batchUpdate"
    resp = _api_request(
        "POST",
        batch_url,
        payload={"requests": [{"insertComment": insert_req}]},
        quota_project=args.project,
        real_binary=real_binary,
        doc_id=doc_id,
    )

    replies = resp.get("replies") or [{}]
    thread = replies[0].get("insertComment", {}).get("commentThread", {})
    comment_id = thread.get("commentId", "")
    anchor_id = thread.get("anchorId", "")
    quoted = thread.get("plainTextQuote", args.quote or "")
    link = build_comment_url(doc_id, comment_id, resolved_tab_id)

    if getattr(args, "json", False):
        out = {
            "documentId": doc_id,
            "commentId": comment_id,
            "anchorId": anchor_id,
            "tabId": resolved_tab_id,
            "startIndex": start_idx,
            "endIndex": end_idx,
            "plainTextQuote": quoted,
            "content": comment_text,
            "link": link,
            "commentThread": thread,
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"Added comment (ID: {comment_id}, Anchor: {anchor_id}, Range: [{start_idx}, {end_idx}])")
        print(f"Link: {link}")
    return 0


def cmd_post_comment(args: argparse.Namespace, real_binary: Optional[str] = None) -> int:
    """Compatibility wrapper for `gdocs_comment.py post --doc-id ... --operator ... --quote ... --content ...`."""
    prefix = f"[AGENT COMMENT — {args.operator}'s Agent on behalf of {args.operator}] "
    full_content = args.content if args.content.startswith("[AGENT COMMENT") else (prefix + args.content)
    shim_args = argparse.Namespace(
        doc_id=args.doc_id,
        comment_text=full_content,
        quote=args.quote,
        start=0,
        end=0,
        tab=getattr(args, "tab", None),
        assignee=None,
        assign=None,
        json=getattr(args, "json", False),
        project=getattr(args, "project", os.environ.get("GDOCS_PROJECT_ID")),
    )
    return cmd_add_comment(shim_args, real_binary=real_binary)


def cmd_make_batch(args: argparse.Namespace) -> int:
    """Generate a Granular Safe Mode `gdocs mutate batch` JSON file for inline shaded agent callouts."""
    ops: List[Dict[str, Any]] = [
        {
            "op": "rich-text",
            "font_family": "Roboto",
            "font_size": 10.5,
            "paragraph_bg_color": args.bg_color,
            "space_above": 6,
            "space_below": 2,
            "runs": [
                {
                    "text": f"[AGENT COMMENT — {args.operator}'s Agent on behalf of {args.operator}]",
                    "bold": True,
                    "font_family": "Roboto",
                    "text_color": args.accent_color,
                }
            ],
        }
    ]
    for idx, b in enumerate(args.bullets):
        if ":" in b:
            head, tail = b.split(":", 1)
            runs = [
                {"text": f"• {head}:", "bold": True, "font_family": "Roboto", "text_color": "#202124"},
                {"text": tail, "bold": False, "font_family": "Roboto", "text_color": "#202124"},
            ]
        else:
            runs = [
                {"text": f"• {b}", "bold": False, "font_family": "Roboto", "text_color": "#202124"},
            ]
        ops.append(
            {
                "op": "rich-text",
                "font_family": "Roboto",
                "font_size": 10.5,
                "paragraph_bg_color": args.bg_color,
                "space_above": 2,
                "space_below": 6 if idx == len(args.bullets) - 1 else 2,
                "runs": runs,
            }
        )

    Path(args.out).write_text(json.dumps(ops, indent=2), encoding="utf-8")
    print(f"✓ Wrote {len(ops)} batch operations to {args.out}")
    return 0


def cmd_reply_comment(args: argparse.Namespace, real_binary: Optional[str] = None) -> int:
    doc_id = args.doc_id
    comment_id = args.comment_id
    reply_text = args.reply_text

    batch_url = f"https://docs.googleapis.com/v1/documents/{urllib.parse.quote(doc_id)}:batchUpdate"
    payload = {
        "requests": [
            {
                "addCommentReply": {
                    "commentId": comment_id,
                    "post": {"content": reply_text},
                }
            }
        ]
    }
    resp = _api_request(
        "POST",
        batch_url,
        payload=payload,
        quota_project=args.project,
        real_binary=real_binary,
        doc_id=doc_id,
    )
    link = build_comment_url(doc_id, comment_id)
    if args.json:
        print(json.dumps(resp, indent=2))
    else:
        print(f"Added reply to comment {comment_id}")
        print(f"Link: {link}")
    return 0


def cmd_delete_comment(args: argparse.Namespace, real_binary: Optional[str] = None) -> int:
    doc_id = args.doc_id
    comment_id = args.comment_id

    batch_url = f"https://docs.googleapis.com/v1/documents/{urllib.parse.quote(doc_id)}:batchUpdate"
    payload = {"requests": [{"deleteComment": {"commentId": comment_id}}]}
    resp = _api_request(
        "POST",
        batch_url,
        payload=payload,
        quota_project=args.project,
        real_binary=real_binary,
        doc_id=doc_id,
    )
    if args.json:
        print(json.dumps(resp, indent=2))
    else:
        print(f"Deleted comment {comment_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gdocs_comment.py",
        description="Add, reply to, or delete native Kix-anchored Google Docs comments via Docs API v1, or generate inline batch callouts.",
    )
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument("--project", default=os.environ.get("GDOCS_PROJECT_ID"), help="GCP quota project ID")
    parser.add_argument("--ignore-sharing-checks", action="store_true", help="Ignore Drive sharing checks")
    parser.add_argument("--legacy-mode", default="deprecated", help="Legacy mode flag compatibility")

    sub = parser.add_subparsers(dest="subcmd")

    # Add comment subcommand (used by transparent gdocs shim and direct CLI)
    add_p = sub.add_parser("add-comment", aliases=["add"], help="Add a native Kix-anchored comment to a Google Doc")
    add_p.add_argument("doc_id", help="Google Doc ID")
    add_p.add_argument("comment_text", help="Comment text")
    add_p.add_argument("--quote", help="Exact text substring to anchor the comment to")
    add_p.add_argument("--start", type=int, default=0, help="Start UTF-16 character index")
    add_p.add_argument("--end", type=int, default=0, help="End UTF-16 character index")
    add_p.add_argument("--tab", help="Tab ID or tab title to anchor the comment to")
    add_p.add_argument("--assignee", help="Email address of user to assign the comment to")
    add_p.add_argument("--assign", help="Alias for --assignee")
    add_p.add_argument("--native", type=str, default="true", help="Use native Google Docs comments API")
    add_p.add_argument("--json", action="store_true", help="Output in JSON format")
    add_p.add_argument("--project", default=os.environ.get("GDOCS_PROJECT_ID"), help="GCP quota project ID")
    add_p.add_argument("--ignore-sharing-checks", action="store_true", help="Ignore Drive sharing checks")
    add_p.add_argument("--legacy-mode", default="deprecated", help="Legacy mode flag compatibility")

    # Post subcommand (Andrew's flag-based syntax, backed by native InsertCommentRequest)
    post_p = sub.add_parser("post", help="Post a native Kix-anchored margin comment with automatic [AGENT COMMENT] prefix")
    post_p.add_argument("--doc-id", required=True, help="Google Doc ID")
    post_p.add_argument("--operator", default="Andrew", help="Operator name for [AGENT COMMENT] header")
    post_p.add_argument("--quote", default=None, help="Exact text substring to anchor the comment to")
    post_p.add_argument("--tab", default=None, help="Tab ID or tab title")
    post_p.add_argument("--content", required=True, help="Comment body text")
    post_p.add_argument("--json", action="store_true", help="Output in JSON format")
    post_p.add_argument("--project", default=os.environ.get("GDOCS_PROJECT_ID"), help="GCP quota project ID")

    # Make-batch subcommand (Andrew's inline callout generator)
    batch_p = sub.add_parser("make-batch", help="Generate inline shaded [AGENT COMMENT] batch JSON")
    batch_p.add_argument("--operator", default="Andrew", help="Operator name")
    batch_p.add_argument("--bg-color", default="#e8f0fe", help="Paragraph background hex color")
    batch_p.add_argument("--accent-color", default="#1a73e8", help="Header text hex color")
    batch_p.add_argument("--bullets", nargs="+", required=True, help="Bullet strings")
    batch_p.add_argument("--out", required=True, help="Output JSON file path")

    # Reply subcommand
    rep_p = sub.add_parser("reply-comment", aliases=["reply"], help="Reply to an existing native comment")
    rep_p.add_argument("doc_id", help="Google Doc ID")
    rep_p.add_argument("comment_id", help="Comment ID (e.g. doco.xxx)")
    rep_p.add_argument("reply_text", help="Reply text")
    rep_p.add_argument("--json", action="store_true", help="Output in JSON format")
    rep_p.add_argument("--project", default=os.environ.get("GDOCS_PROJECT_ID"), help="GCP quota project ID")

    # Delete subcommand
    del_p = sub.add_parser("delete-comment", aliases=["delete"], help="Delete a native comment by ID")
    del_p.add_argument("doc_id", help="Google Doc ID")
    del_p.add_argument("comment_id", help="Comment ID (e.g. doco.xxx)")
    del_p.add_argument("--json", action="store_true", help="Output in JSON format")
    del_p.add_argument("--project", default=os.environ.get("GDOCS_PROJECT_ID"), help="GCP quota project ID")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    real_binary = os.environ.get("GDOCS_REAL_BINARY")

    normalized = list(argv)
    if normalized and normalized[0] == "mutate":
        normalized = normalized[1:]
    if normalized and normalized[0] not in (
        "add-comment",
        "add",
        "post",
        "make-batch",
        "reply-comment",
        "reply",
        "delete-comment",
        "delete",
        "-h",
        "--help",
    ):
        normalized = ["add-comment"] + normalized

    parser = build_parser()
    args = parser.parse_args(normalized)

    if not args.subcmd:
        parser.print_help()
        return 1

    try:
        if args.subcmd in ("add-comment", "add"):
            return cmd_add_comment(args, real_binary=real_binary)
        if args.subcmd == "post":
            return cmd_post_comment(args, real_binary=real_binary)
        if args.subcmd == "make-batch":
            return cmd_make_batch(args)
        if args.subcmd in ("reply-comment", "reply"):
            return cmd_reply_comment(args, real_binary=real_binary)
        if args.subcmd in ("delete-comment", "delete"):
            return cmd_delete_comment(args, real_binary=real_binary)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

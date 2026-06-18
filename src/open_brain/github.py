"""GitHub issue and pull-request ingestion."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from typing import Any

from .brain import BrainService
from .errors import GitHubIngestError

GITHUB_API = "https://api.github.com"


def ingest_issue(args: argparse.Namespace) -> int:
    brain = BrainService(db_path=args.db)
    result = ingest_github_issue(
        brain,
        repo=args.repo,
        number=int(args.number),
        token=args.token or os.getenv("GITHUB_TOKEN"),
    )
    print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    return 0


def ingest_pr(args: argparse.Namespace) -> int:
    brain = BrainService(db_path=args.db)
    result = ingest_github_pr(
        brain,
        repo=args.repo,
        number=int(args.number),
        token=args.token or os.getenv("GITHUB_TOKEN"),
        include_diff=args.include_diff,
    )
    print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    return 0


def ingest_github_issue(
    brain: BrainService,
    *,
    repo: str,
    number: int,
    token: str | None = None,
) -> dict[str, Any]:
    """Fetch and ingest one GitHub issue plus comments."""

    issue = _fetch_json(f"/repos/{repo}/issues/{number}", token=token)
    comments = _fetch_json(f"/repos/{repo}/issues/{number}/comments", token=token)
    if not isinstance(comments, list):
        comments = []
    content = _render_issue(repo, issue, comments)
    result = brain.ingest(
        content,
        source="github",
        kind="issue",
        workspace=repo,
        actor=(issue.get("user") or {}).get("login", "unknown"),
        source_id=f"issue:{number}",
        idempotency_key=f"github:{repo}:issue:{number}:updated:{issue.get('updated_at')}",
        metadata={
            "repo": repo,
            "number": number,
            "url": issue.get("html_url"),
            "comments": len(comments),
        },
    )
    return {"ingest": result, "comments": len(comments), "url": issue.get("html_url")}


def ingest_github_pr(
    brain: BrainService,
    *,
    repo: str,
    number: int,
    token: str | None = None,
    include_diff: bool = False,
) -> dict[str, Any]:
    """Fetch and ingest one GitHub pull request plus comments and optional diff."""

    pr = _fetch_json(f"/repos/{repo}/pulls/{number}", token=token)
    comments = _fetch_json(f"/repos/{repo}/issues/{number}/comments", token=token)
    review_comments = _fetch_json(f"/repos/{repo}/pulls/{number}/comments", token=token)
    if not isinstance(comments, list):
        comments = []
    if not isinstance(review_comments, list):
        review_comments = []
    diff = _fetch_text(f"/repos/{repo}/pulls/{number}", token=token, accept="application/vnd.github.v3.diff") if include_diff else ""
    content = _render_pr(repo, pr, comments, review_comments, diff)
    result = brain.ingest(
        content,
        source="github",
        kind="pull_request",
        workspace=repo,
        actor=(pr.get("user") or {}).get("login", "unknown"),
        source_id=f"pr:{number}",
        idempotency_key=f"github:{repo}:pr:{number}:updated:{pr.get('updated_at')}:diff:{bool(diff)}",
        metadata={
            "repo": repo,
            "number": number,
            "url": pr.get("html_url"),
            "comments": len(comments),
            "review_comments": len(review_comments),
            "include_diff": include_diff,
        },
    )
    return {
        "ingest": result,
        "comments": len(comments),
        "review_comments": len(review_comments),
        "url": pr.get("html_url"),
    }


def _fetch_json(path: str, *, token: str | None = None) -> Any:
    raw = _fetch_text(path, token=token, accept="application/vnd.github+json")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubIngestError(f"GitHub returned invalid JSON for {path}") from exc


def _fetch_text(path: str, *, token: str | None = None, accept: str = "application/vnd.github+json") -> str:
    request = urllib.request.Request(
        GITHUB_API + path,
        headers={
            "Accept": accept,
            "User-Agent": "open-brain-plugin/0.1.0",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise GitHubIngestError(f"GitHub HTTP {exc.code} for {path}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise GitHubIngestError(f"GitHub request failed for {path}: {exc}") from exc


def _render_issue(repo: str, issue: dict[str, Any], comments: list[dict[str, Any]]) -> str:
    lines = [
        f"GitHub Issue: {repo}#{issue.get('number')} {issue.get('title', '')}",
        f"State: {issue.get('state')} Author: {(issue.get('user') or {}).get('login', 'unknown')}",
        f"URL: {issue.get('html_url')}",
        "",
        issue.get("body") or "",
    ]
    for comment in comments:
        lines.extend(
            [
                "",
                f"Comment by {(comment.get('user') or {}).get('login', 'unknown')} at {comment.get('created_at')}:",
                comment.get("body") or "",
            ]
        )
    return "\n".join(lines)


def _render_pr(
    repo: str,
    pr: dict[str, Any],
    comments: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    diff: str,
) -> str:
    lines = [
        f"GitHub Pull Request: {repo}#{pr.get('number')} {pr.get('title', '')}",
        f"State: {pr.get('state')} Author: {(pr.get('user') or {}).get('login', 'unknown')}",
        f"URL: {pr.get('html_url')}",
        "",
        pr.get("body") or "",
    ]
    for comment in comments:
        lines.extend(
            [
                "",
                f"Issue comment by {(comment.get('user') or {}).get('login', 'unknown')} at {comment.get('created_at')}:",
                comment.get("body") or "",
            ]
        )
    for comment in review_comments:
        lines.extend(
            [
                "",
                f"Review comment by {(comment.get('user') or {}).get('login', 'unknown')} on {comment.get('path')}:{comment.get('line')}:",
                comment.get("body") or "",
            ]
        )
    if diff:
        lines.extend(["", "Diff:", diff[:180_000]])
    return "\n".join(lines)


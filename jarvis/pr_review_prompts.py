"""PR review prompt templates.

Two modes, detected from authorship:

- **External PR** (author != my gh account): produce a human handoff —
  path:line comments + a concise verdict line. Designed to be pasted into
  GitHub's review UI.
- **Own PR** (author == my gh account): produce a ready-to-paste *prompt*
  for the authoring conversation asking Claude to fix each finding. Keeps
  the fix-loop short: copy, paste, push.

Both end with a single machine-readable verdict line. That line feeds the
severity badge on the PR card without needing a second LLM call.
"""

from __future__ import annotations

import re
from typing import Any

VERDICT_KEYS = ("lgtm", "lgtm-with-nits", "appreciate-changes", "changes-requested")

_VERDICT_RE = re.compile(
    r"^VERDICT:\s*(lgtm-with-nits|lgtm|appreciate-changes|changes-requested)"
    r"\s*\((\d+)\s*must-fix,\s*(\d+)\s*nits?\)\s*$",
    re.MULTILINE,
)

_VERDICT_INSTRUCTION = (
    "\n\nAfter your findings, end your response with exactly one machine-readable line"
    " in this format (no backticks, no extras):\n"
    "`VERDICT: <lgtm|lgtm-with-nits|appreciate-changes|changes-requested>"
    " (<M> must-fix, <N> nits)`\n"
    "Rules: `lgtm` when 0 must-fix and 0 nits; `lgtm-with-nits` when 0 must-fix and ≥1 nits;"
    " `appreciate-changes` when ≥1 must-fix but the PR could still ship;"
    " `changes-requested` when at least one must-fix blocks merging."
)

_SEVERITY_LEGEND = (
    "Tag each finding with one of: 🔴 must-fix (blocks merging), 🟡 nit"
    " (style/polish), 🟢 question (not an issue, just a clarification)."
)


def _header(pr_info: dict[str, Any], sub: dict[str, Any], repo: str, pr_number: int) -> str:
    title = pr_info.get("title") or sub.get("title") or ""
    parts = [f"**{title}**", f"Repo: {repo} | PR #{pr_number}"]
    if pr_info.get("author"):
        parts.append(f"Author: {pr_info['author']}")
    if pr_info.get("body"):
        parts.append(f"\n**Description:**\n{pr_info['body']}")
    ci = sub.get("ci_status") or "unknown"
    rd = sub.get("review_decision") or "pending"
    parts.append(f"\n**CI:** {ci} | **Reviews:** {rd}")
    return "\n".join(parts)


def build_review_prompt(
    pr_info: dict[str, Any],
    sub: dict[str, Any],
    repo: str,
    pr_number: int,
    diff_text: str,
    *,
    is_own_pr: bool,
) -> str:
    header = _header(pr_info, sub, repo, pr_number)
    diff_block = f"\n**Diff:**\n```diff\n{diff_text}\n```"

    if is_own_pr:
        branch = pr_info.get("headRefName") or sub.get("branch") or ""
        body = (
            f"\n\nPlease review my PR and produce a ready-to-paste prompt I can"
            f" drop into the authoring conversation to fix the issues. Review the"
            f" diff below — don't read other files unless you explicitly need to.\n\n"
            f"{_SEVERITY_LEGEND}\n\n"
            f"Output exactly this structure:\n\n"
            f"## Fix prompt\n"
            f"```\n"
            f"Fix the following in this PR (branch `{branch}`,"
            f" PR #{pr_number}). Keep the diff minimal. After pushing, reply with a"
            f" one-line summary of what changed.\n\n"
            f"<enumerate each finding as: - [severity] path:line — concern>\n"
            f"```\n\n"
            f"## Notes\n"
            f"One short paragraph on anything worth flagging that isn't in the fix prompt"
            f" (architectural observations, optional improvements)."
        )
    else:
        body = (
            f"\n\nPlease review this PR as a code reviewer handing feedback to the author."
            f" Review the diff below — don't read other files unless you explicitly need to.\n\n"
            f"{_SEVERITY_LEGEND}\n\n"
            f"Output exactly this structure:\n\n"
            f"## Inline comments\n"
            f"One block per finding, copy-paste-ready for GitHub:\n"
            f"- **`path/to/file.py:42`** — [severity] concise comment written at the author,"
            f" friendly and specific.\n\n"
            f"## Summary\n"
            f"Two or three sentences for the GitHub review body: what looks good, what"
            f" must change, what's optional. End with one of the verdict phrases"
            f" (LGTM / LGTM with nits / would appreciate N changes before merging /"
            f" changes requested — N must-fix)."
        )

    return header + body + diff_block + _VERDICT_INSTRUCTION


def build_rereview_prompt(
    pr_info: dict[str, Any],
    sub: dict[str, Any],
    repo: str,
    pr_number: int,
    diff_text: str,
    *,
    is_own_pr: bool,
    prior_review_md: str | None = None,
) -> str:
    header = _header(pr_info, sub, repo, pr_number)
    diff_block = f"\n**Latest diff:**\n```diff\n{diff_text}\n```"

    prior_block = ""
    if prior_review_md:
        # Trim aggressively — the model only needs the findings, not the whole
        # response, to avoid blowing the prompt budget on re-reviews of large
        # PRs.
        trimmed = prior_review_md.strip()
        if len(trimmed) > 4000:
            trimmed = trimmed[:4000] + "\n…(truncated)"
        prior_block = (
            f"\n\n**Prior review (reference: say what's fixed, still open,"
            f" or newly added):**\n{trimmed}"
        )

    mode = "own" if is_own_pr else "external"
    body = (
        f"\n\nRe-review this PR ({mode}-author mode). Keep the same output"
        f" structure as the first review, but organise the findings under these"
        f" headings:\n"
        f"- **Fixed** — items from the prior review that are now resolved.\n"
        f"- **Still open** — items from the prior review that are not yet addressed.\n"
        f"- **New** — issues introduced since the prior review.\n\n"
        f"{_SEVERITY_LEGEND}"
    )

    return header + prior_block + body + diff_block + _VERDICT_INSTRUCTION


def parse_verdict(text: str) -> dict[str, Any] | None:
    """Pull the VERDICT line out of a completed review response.

    Returns {verdict, must_fix, nits} or None if no match. Searches
    bottom-up since the instruction asks models to put the line last.
    """
    if not text:
        return None
    # Find the last match (in case the model quoted the instruction earlier).
    last: re.Match[str] | None = None
    for m in _VERDICT_RE.finditer(text):
        last = m
    if not last:
        return None
    return {
        "verdict": last.group(1),
        "must_fix": int(last.group(2)),
        "nits": int(last.group(3)),
    }

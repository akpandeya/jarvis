"""Tests for jarvis/pr_review_prompts.py — prompt templates + verdict parser."""

from __future__ import annotations

import pytest

from jarvis.pr_review_prompts import (
    build_rereview_prompt,
    build_review_prompt,
    parse_verdict,
)

PR_INFO = {
    "title": "Add thing",
    "body": "Some description.",
    "author": "external-dev",
    "headRefName": "feat/x",
}
SUB = {"ci_status": "passed", "review_decision": "pending", "branch": "feat/x"}


# --- Prompt templates ---


def test_external_prompt_targets_inline_comments():
    p = build_review_prompt(PR_INFO, SUB, "me/jarvis", 42, "diff-goes-here", is_own_pr=False)
    assert "Inline comments" in p
    assert "copy-paste-ready for GitHub" in p
    assert "diff-goes-here" in p
    assert "VERDICT:" in p
    assert "Fix prompt" not in p


def test_own_prompt_produces_fix_prompt():
    p = build_review_prompt(PR_INFO, SUB, "me/jarvis", 42, "diff-x", is_own_pr=True)
    assert "Fix prompt" in p
    assert "feat/x" in p  # branch threaded into the fix prompt
    assert "Inline comments" not in p
    assert "VERDICT:" in p


def test_prompts_include_severity_legend_and_verdict_instruction():
    for is_own in (True, False):
        p = build_review_prompt(PR_INFO, SUB, "me/j", 1, "d", is_own_pr=is_own)
        assert "must-fix" in p
        assert "nit" in p
        assert "changes-requested" in p


def test_rereview_includes_prior_review_when_provided():
    p = build_rereview_prompt(
        PR_INFO,
        SUB,
        "me/j",
        1,
        "new-diff",
        is_own_pr=False,
        prior_review_md="The old review found X and Y.",
    )
    assert "Prior review" in p
    assert "The old review found X and Y." in p
    assert "Fixed" in p and "Still open" in p and "New" in p


def test_rereview_truncates_giant_prior():
    prior = "A" * 9000
    p = build_rereview_prompt(PR_INFO, SUB, "me/j", 1, "d", is_own_pr=False, prior_review_md=prior)
    assert "(truncated)" in p
    # Shouldn't contain the whole blob
    assert p.count("A") < 6000


# --- Verdict parser ---


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "Some review.\n\nVERDICT: lgtm (0 must-fix, 0 nits)",
            {"verdict": "lgtm", "must_fix": 0, "nits": 0},
        ),
        (
            "details.\nVERDICT: lgtm-with-nits (0 must-fix, 3 nits)",
            {"verdict": "lgtm-with-nits", "must_fix": 0, "nits": 3},
        ),
        (
            "stuff.\nVERDICT: appreciate-changes (2 must-fix, 1 nit)",
            {"verdict": "appreciate-changes", "must_fix": 2, "nits": 1},
        ),
        (
            "full.\nVERDICT: changes-requested (5 must-fix, 0 nits)",
            {"verdict": "changes-requested", "must_fix": 5, "nits": 0},
        ),
    ],
)
def test_parse_verdict_happy_path(text, expected):
    assert parse_verdict(text) == expected


def test_parse_verdict_picks_last_match_when_instruction_quoted():
    text = (
        "The format is `VERDICT: <lgtm|lgtm-with-nits|...> (M must-fix, N nits)`.\n"
        "Findings...\n"
        "VERDICT: lgtm (0 must-fix, 0 nits)\n"
    )
    # The quoted instruction isn't a literal verdict match (no digits), so
    # only the real one is captured. Verify it's picked either way.
    assert parse_verdict(text) == {"verdict": "lgtm", "must_fix": 0, "nits": 0}


def test_parse_verdict_returns_none_when_absent():
    assert parse_verdict("no verdict line here") is None
    assert parse_verdict("") is None
    assert parse_verdict("VERDICT: maybe") is None

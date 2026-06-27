#!/usr/bin/env python3
"""Check whether a saved Blue Team report is skim-friendly.

This is intentionally lightweight. It does not judge correctness; it catches output-shape
problems that make findings hard to scan in the web UI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

JSON_BLOCK_RE = re.compile(r"```json[ \t]*\n([\s\S]*?)```")
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+./%-]*")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

JARGON = {
    "affordance",
    "contract",
    "reader-facing",
    "topline",
    "provenance",
}


def words(text: str) -> list[str]:
    return WORD_RE.findall(text or "")


def sentence_count(text: str) -> int:
    parts = [p.strip() for p in SENTENCE_RE.split((text or "").strip()) if p.strip()]
    return len(parts)


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]


def load_findings(path: Path) -> list[dict]:
    text = path.read_text(errors="replace")
    blocks = JSON_BLOCK_RE.findall(text)
    if not blocks:
        raise ValueError("no ```json findings block found")
    obj = json.loads(blocks[-1])
    findings = obj.get("findings")
    if not isinstance(findings, list):
        raise ValueError("JSON block does not contain a findings list")
    return findings


def check(path: Path) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    findings = load_findings(path)

    for i, finding in enumerate(findings, 1):
        title = str(finding.get("title") or "")
        context = str(finding.get("context") or "")
        issue = str(finding.get("issue") or "")
        mechanism = str(finding.get("mechanism") or "")
        prefix = f"finding {i} ({title[:60] or 'untitled'})"

        title_words = len(words(title))
        context_words = len(words(context))
        issue_words = len(words(issue))
        mechanism_words = len(words(mechanism))

        if title_words > 18:
            failures.append(f"{prefix}: title has {title_words} words (>18)")
        if context and context_words < 80:
            failures.append(f"{prefix}: context has {context_words} words (<80)")
        if context_words > 200:
            failures.append(f"{prefix}: context has {context_words} words (>200)")
        elif context_words > 170:
            warnings.append(
                f"{prefix}: context has {context_words} words (>170 target)"
            )
        if issue and issue_words < 40:
            failures.append(f"{prefix}: issue has {issue_words} words (<40)")
        if issue_words > 100:
            failures.append(f"{prefix}: issue has {issue_words} words (>100)")
        elif issue_words > 95:
            warnings.append(f"{prefix}: issue has {issue_words} words (>95 target)")
        if mechanism and mechanism_words < 45:
            failures.append(f"{prefix}: mechanism has {mechanism_words} words (<45)")
        if mechanism_words > 95:
            failures.append(f"{prefix}: mechanism has {mechanism_words} words (>95)")

        issue_sentences = sentence_count(issue)
        mechanism_sentences = sentence_count(mechanism)
        context_paragraphs = paragraphs(context)
        if context and len(context_paragraphs) != 2:
            failures.append(
                f"{prefix}: context has {len(context_paragraphs)} paragraphs (target 2)"
            )
        for n, para in enumerate(context_paragraphs, 1):
            para_words = len(words(para))
            para_sentences = sentence_count(para)
            if para_words < 35:
                failures.append(
                    f"{prefix}: context paragraph {n} has {para_words} words (<35)"
                )
            if para_words > 90:
                failures.append(
                    f"{prefix}: context paragraph {n} has {para_words} words (>90)"
                )
            if para_sentences < 2:
                failures.append(
                    f"{prefix}: context paragraph {n} has {para_sentences} sentence"
                )
        if issue and not (2 <= issue_sentences <= 4):
            warnings.append(
                f"{prefix}: issue has {issue_sentences} sentences (target 2-4)"
            )
        if mechanism and not (2 <= mechanism_sentences <= 3):
            warnings.append(
                f"{prefix}: mechanism has {mechanism_sentences} sentences (target 2-3)"
            )

        lower_text = f"{title}\n{context}\n{issue}\n{mechanism}".lower()
        for term in sorted(JARGON):
            if term in lower_text:
                failures.append(f"{prefix}: contains audit jargon {term!r}")

        if not context:
            failures.append(f"{prefix}: missing context")
        if not issue:
            failures.append(f"{prefix}: missing issue")
        if not mechanism:
            failures.append(f"{prefix}: missing mechanism")

    return failures, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()

    any_failed = False
    for report in args.reports:
        try:
            failures, warnings = check(report)
        except Exception as exc:  # noqa: BLE001 - CLI should report bad inputs plainly.
            print(f"{report}: ERROR: {exc}", file=sys.stderr)
            any_failed = True
            continue

        if failures or warnings:
            print(f"{report}:")
            for item in failures:
                print(f"  FAIL {item}")
            for item in warnings:
                print(f"  WARN {item}")
        else:
            print(f"{report}: OK")
        any_failed = any_failed or bool(failures)

    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Refuse to let a placeholder reach a judge.

Scans every judge-facing file for the four things that quietly survive into a submission
and destroy it on sight: an unfilled address, a fake video link, a TODO, and a template
token nobody replaced.

    python3 scripts/check_submission_readiness.py          # exit 1 on any finding
    python3 scripts/check_submission_readiness.py --json

Exit 0 = clean. Exit 1 = something is not ready. Wire it into `make check`.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Files a judge actually opens. Deliberately narrow: a TODO in a source comment is
# ordinary engineering, a TODO in the README is an unfinished submission.
TARGETS = ["README.md", "DEMO.md", "JUDGE.md", "FEEDBACK.md", "ARCHITECTURE.md"]
TARGET_GLOBS = ["docs/*.md", ".github/*.md"]

PATTERNS = [
    ("unfilled address", r"0x\.\.\."),
    ("placeholder video", r"youtu\.be/(xxx|your-video|VIDEO_ID)\b"),
    ("placeholder video", r"youtube\.com/watch\?v=(xxx|your-video|VIDEO_ID)\b"),
    ("TODO marker", r"\bTODO\b"),
    ("TODO marker", r"\bFIXME\b"),
    ("unreplaced template token", r"\[\[FILL\]\]"),
    ("unreplaced template token", r"\[Project Name\]"),
    ("unreplaced template token", r"\bOWNER/REPO\b"),
    ("unreplaced template token", r"\[your-[a-z-]+\]"),
    ("placeholder URL", r"https?://\[[a-z-]+\]"),
    ("placeholder URL", r"example\.com/(your|placeholder)"),
]

# A line that is itself the definition of a pattern is not a violation.
SELF_REFERENTIAL = re.compile(r"placeholder|readiness|scanner|check_submission")


def scan():
    files = [ROOT / t for t in TARGETS if (ROOT / t).exists()]
    for g in TARGET_GLOBS:
        files += sorted(ROOT.glob(g))
    findings = []
    for f in sorted(set(files)):
        for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            if SELF_REFERENTIAL.search(line):
                continue
            for label, pat in PATTERNS:
                if re.search(pat, line, re.IGNORECASE if "youtu" in pat else 0):
                    findings.append(
                        {
                            "file": str(f.relative_to(ROOT)),
                            "line": n,
                            "kind": label,
                            "text": line.strip()[:110],
                        }
                    )
                    break
    return [str(f.relative_to(ROOT)) for f in sorted(set(files))], findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    scanned, findings = scan()

    if a.json:
        print(json.dumps({"scanned": scanned, "findings": findings}, indent=2))
    else:
        print(f"submission readiness — scanned {len(scanned)} judge-facing file(s)")
        for s in scanned:
            print(f"  · {s}")
        if findings:
            print(f"\n{len(findings)} placeholder(s) still in the submission:\n")
            for f in findings:
                print(f"  {f['file']}:{f['line']}  [{f['kind']}]  {f['text']}")
        else:
            print("\nclean — no unfilled addresses, fake links, TODOs or template tokens")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

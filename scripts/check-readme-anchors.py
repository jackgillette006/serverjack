#!/usr/bin/env python3
"""A14: checks every in-page `](#anchor)` link in README.md actually
resolves to a real heading, GitHub's own slug rules (lowercase, spaces to
hyphens, punctuation stripped, duplicates disambiguated with -1/-2/...).
Catches drift like line 511's [Updating and rolling back](#update-serverjack)
-- link text naming one section, href pointing at a different, existing one
(so a plain "anchor doesn't exist" grep would have missed it too; this
diffs the actual target).

Usage: python3 scripts/check-readme-anchors.py [FILE ...]  (default: README.md)
Exit 0 if every anchor resolves, 1 otherwise (prints each broken one).
"""
import re
import sys


def slugify(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[`*_]", "", s)          # inline code/emphasis markers
    s = re.sub(r"[^\w\s-]", "", s)       # punctuation
    s = re.sub(r"\s+", "-", s)
    return s


def check(path: str) -> list[str]:
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()

    seen = {}
    valid = set()
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if not m:
            continue
        slug = slugify(m.group(2))
        n = seen.get(slug, 0)
        valid.add(slug if n == 0 else f"{slug}-{n}")
        seen[slug] = n + 1

    problems = []
    in_code_fence = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        for m in re.finditer(r"\]\(#([A-Za-z0-9][A-Za-z0-9-]*)\)", line):
            anchor = m.group(1)
            if anchor not in valid:
                problems.append(f"{path}:{i}: #{anchor} does not match any heading -- {line.strip()[:100]}")
    return problems


def main() -> int:
    paths = sys.argv[1:] or ["README.md"]
    problems = []
    for p in paths:
        problems.extend(check(p))
    if problems:
        print(f"{len(problems)} broken anchor link(s):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"OK: every anchor link in {', '.join(paths)} resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
update_md.py — Post-process all course markdown files to:

  1. Regenerate (or insert) a ## Table of Contents after the H1 / opening block.
  2. Add a "↑ Back to TOC" link at the bottom of every ## section.
  3. Add / replace the copyright footer at the end of each file.

Run from the course directory:
  python3 update_md.py
"""

import re
from pathlib import Path

COURSE_DIR = Path(__file__).parent

MD_FILES = [
    "README.md",
    "00-setup-lab-environment.md",
    "01-introduction-and-architecture.md",
    "02-nftables-fundamentals.md",
    "03-zones-and-trust-model.md",
    "04-services-ports-and-protocols.md",
    "05-policies-and-inter-zone-routing.md",
    "06-rich-rules.md",
    "07-nat-masquerading-and-port-forwarding.md",
    "08-container-integration.md",
    "09-ipsets-and-dynamic-filtering.md",
    "10-logging-troubleshooting-and-debugging.md",
    "11-lockdown-mode-and-hardening.md",
    "12-direct-rules-and-advanced-nftables.md",
    "13-capstone-project.md",
    "cheatsheet.md",
    "faq.md",
]

COPYRIGHT_LINE = "© 2026 UncleJS — Licensed under CC BY-NC-SA 4.0"
BACK_TO_TOC = "\n\n---\n\n↑ [Back to TOC](#table-of-contents)"


# ---------------------------------------------------------------------------
# Slug generation (GitHub-flavour Markdown anchors)
# ---------------------------------------------------------------------------

def slugify(heading: str) -> str:
    """
    Convert a heading string to a GitHub-flavour anchor slug.
    Rules:
      - Strip inline markdown (bold, italic, code, links)
      - Lowercase everything
      - Replace spaces with hyphens
      - Remove all characters that are not alphanumeric, hyphen, or space
    """
    # strip inline markdown
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', heading)   # [text](url) → text
    s = re.sub(r'`([^`]+)`', r'\1', s)                     # `code`
    s = re.sub(r'\*\*([^*]+)\*\*', r'\1', s)               # **bold**
    s = re.sub(r'\*([^*]+)\*', r'\1', s)                   # *italic*
    s = re.sub(r'__([^_]+)__', r'\1', s)                   # __bold__
    s = re.sub(r'_([^_]+)_', r'\1', s)                     # _italic_
    # lowercase
    s = s.lower()
    # keep only alphanumeric, spaces, hyphens
    s = re.sub(r'[^\w\s-]', '', s)
    # replace whitespace with hyphens
    s = re.sub(r'\s+', '-', s.strip())
    # collapse multiple hyphens
    s = re.sub(r'-+', '-', s)
    return s


# ---------------------------------------------------------------------------
# Build TOC lines from a list of (level, heading_text) tuples
# Only ## headings (level 2) are included; exclude the TOC heading itself.
# ---------------------------------------------------------------------------

def build_toc(headings: list) -> str:
    """
    headings: list of heading strings (## text already stripped of '## ').
    Returns a markdown TOC block (no leading/trailing blank lines).
    """
    lines = ["## Table of Contents", ""]
    # Track slugs to handle duplicates (GitHub appends -1, -2, etc.)
    slug_count: dict = {}
    for i, text in enumerate(headings, start=1):
        slug = slugify(text)
        if slug in slug_count:
            slug_count[slug] += 1
            slug = f"{slug}-{slug_count[slug]}"
        else:
            slug_count[slug] = 0
        lines.append(f"{i}. [{text}](#{slug})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

def process_file(path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    text = original

    # -----------------------------------------------------------------------
    # Step 0: strip any existing copyright footer from the very end
    # -----------------------------------------------------------------------
    # Match a trailing block: optional whitespace, optional ---, optional
    # whitespace, then the copyright line (possibly already present).
    text = re.sub(
        r'\n+---\n+©[^\n]*\n*$',
        '',
        text,
        flags=re.MULTILINE,
    )
    # Also strip a bare copyright line at the very end (no ---)
    text = re.sub(r'\n+©[^\n]*\n*$', '', text)
    text = text.rstrip()

    # -----------------------------------------------------------------------
    # Step 1: Remove any existing ## Table of Contents block
    # -----------------------------------------------------------------------
    # Match "## Table of Contents" through the next "## " heading or end of file,
    # consuming the blank lines before the next heading too.
    text = re.sub(
        r'^## Table of Contents\b.*?(?=^## |\Z)',
        '',
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    # Clean up resulting blank lines (keep at most 2 consecutive)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # -----------------------------------------------------------------------
    # Step 2: Remove any existing "↑ Back to TOC" lines (and their surrounding ---)
    # We'll re-add them cleanly in step 4.
    # Pattern: optional blank, ---, blank, ↑ [Back to TOC](...) , optional blank
    # -----------------------------------------------------------------------
    text = re.sub(
        r'\n+---\n+↑ \[Back to TOC\]\([^)]+\)',
        '',
        text,
    )

    # -----------------------------------------------------------------------
    # Step 3: Collect all ## headings (excluding ToC itself) to build the TOC
    # -----------------------------------------------------------------------
    h2_headings = [
        m.group(1).strip()
        for m in re.finditer(r'^## (.+)$', text, flags=re.MULTILINE)
        if not re.match(r'^[Tt]able\s+of\s+[Cc]ontents', m.group(1).strip())
    ]

    toc_block = build_toc(h2_headings)

    # -----------------------------------------------------------------------
    # Step 4: Find the insertion point for the TOC
    #
    # Strategy (in priority order):
    #   a) After the opening blockquote block ("> Goal: …") + "---"
    #   b) After the first "---" that follows the H1
    #   c) Immediately after the H1 line
    # -----------------------------------------------------------------------
    lines = text.splitlines()

    # Find H1 line index
    h1_idx = next(
        (i for i, l in enumerate(lines) if l.startswith('# ') and not l.startswith('## ')),
        0,
    )

    # Determine insertion index
    insert_after = h1_idx  # default: right after H1

    # Look for a blockquote block followed by a "---" separator
    i = h1_idx + 1
    in_bq = False
    bq_end = None
    while i < len(lines):
        l = lines[i].strip()
        if l.startswith('>'):
            in_bq = True
            i += 1
            continue
        if in_bq and l == '':
            i += 1
            continue
        if in_bq and l == '---':
            bq_end = i
            break
        if in_bq:
            # blockquote ended without a separator
            break
        if l == '---':
            bq_end = i
            break
        if l.startswith('## ') or l.startswith('# '):
            break
        i += 1

    if bq_end is not None:
        insert_after = bq_end  # insert AFTER this "---" line

    # Rebuild the document with TOC inserted
    before = lines[: insert_after + 1]
    after  = lines[insert_after + 1 :]

    # Strip blank lines at the join points for a clean result
    while before and before[-1].strip() == '':
        before.pop()
    while after and after[0].strip() == '':
        after.pop(0)

    # The TOC block ends cleanly; the first ## section below will get a Back-to-TOC
    # prefix that already includes a "---" separator, so we do NOT emit one here.
    new_lines = before + ['', ''] + toc_block.splitlines() + [''] + after

    text = '\n'.join(new_lines)

    # -----------------------------------------------------------------------
    # Step 5: Insert "↑ Back to TOC" before each ## heading,
    # EXCEPT the ## Table of Contents heading itself.
    #
    # The Back-to-TOC block is:   \n\n---\n\n↑ [Back to TOC](…)
    # Any existing "---" line immediately before the heading will be absorbed
    # by stripping trailing "---" from the content block before inserting.
    # -----------------------------------------------------------------------
    parts = re.split(r'\n(## .+)', text)
    # parts[0]                           = everything before first ##
    # parts[1], parts[3], parts[5], ...  = heading lines
    # parts[2], parts[4], parts[6], ...  = content after each heading

    if len(parts) > 1:
        result_parts = [parts[0]]
        for idx in range(1, len(parts), 2):
            heading_line = parts[idx]
            content = parts[idx + 1] if idx + 1 < len(parts) else ''
            heading_text = heading_line[3:].strip()

            if re.match(r'^[Tt]able\s+of\s+[Cc]ontents', heading_text):
                # No back-to-toc before the TOC itself
                result_parts.append('\n' + heading_line + content)
            else:
                # Strip any trailing "---" + blank lines from the preceding content
                # so we don't get a double horizontal rule
                preceding = result_parts[-1].rstrip()
                preceding = re.sub(r'\n---\s*$', '', preceding)
                result_parts[-1] = preceding
                result_parts.append(BACK_TO_TOC + '\n\n' + heading_line + content)

        text = ''.join(result_parts)

    # Clean up: no more than 2 consecutive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # -----------------------------------------------------------------------
    # Step 6: Append copyright footer
    # -----------------------------------------------------------------------
    text = text.rstrip()
    text += f"\n\n---\n\n{COPYRIGHT_LINE}\n"

    # -----------------------------------------------------------------------
    # Write back only if changed
    # -----------------------------------------------------------------------
    if text != original:
        path.write_text(text, encoding="utf-8")
        print(f"  updated  {path.name}")
    else:
        print(f"  no-op    {path.name}")


def main():
    print("Processing markdown files …\n")
    for name in MD_FILES:
        p = COURSE_DIR / name
        if not p.exists():
            print(f"  MISSING  {name}")
            continue
        process_file(p)
    print("\nDone.")


if __name__ == "__main__":
    main()

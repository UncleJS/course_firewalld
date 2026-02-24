#!/usr/bin/env python3
"""
build_slides.py — Generate ODP slide decks from the course_firewalld markdown modules.

Colour theme: RHEL Red / Dark
  Background  #1A1A1A  near-black
  Title text  #EE0000  RHEL red
  Body text   #F0F0F0  off-white
  Code bg     #2D2D2D  dark grey
  Code text   #A8FF60  terminal green
  Lab accent  #CC0000  darker red (banner)
  Lab bg      #2A0000  very dark red

Output: slides/<source-stem>.odp  (one file per markdown module)

Usage:
  python3 build_slides.py
"""

import os
import re
from pathlib import Path

from odf.opendocument import OpenDocumentPresentation
from odf.style import (
    Style, MasterPage, PageLayout, PageLayoutProperties,
    TextProperties, GraphicProperties, ParagraphProperties,
    DrawingPageProperties,
)
from odf.text import P, Span, LineBreak
from odf.draw import Page, Frame, TextBox
from odf.presentation import Notes
from odf.table import Table, TableRow, TableCell, TableColumn
from odf.namespaces import PRESENTATIONNS, STYLENS, FONS
from odf.element import Element

# ---------------------------------------------------------------------------
# Slide canvas — 16:9 widescreen
# ---------------------------------------------------------------------------
SLIDE_W = "33.87cm"
SLIDE_H = "19.05cm"

# ---------------------------------------------------------------------------
# Colour palette (RHEL Red / Dark)
# ---------------------------------------------------------------------------
C_BG       = "#1A1A1A"
C_BG_CODE  = "#2D2D2D"
C_BG_LAB   = "#2A0000"
C_RED      = "#EE0000"
C_RED_DARK = "#CC0000"
C_WHITE    = "#F0F0F0"
C_GREEN    = "#A8FF60"
C_GREY     = "#888888"

# ---------------------------------------------------------------------------
# Source → output mapping
# ---------------------------------------------------------------------------
COURSE_DIR = Path(__file__).parent
SLIDES_DIR = COURSE_DIR / "slides"

SOURCE_FILES = [
    ("README.md",                                    "00-overview.odp"),
    ("00-setup-lab-environment.md",                  "00-setup-lab-environment.odp"),
    ("01-introduction-and-architecture.md",          "01-introduction-and-architecture.odp"),
    ("02-nftables-fundamentals.md",                  "02-nftables-fundamentals.odp"),
    ("03-zones-and-trust-model.md",                  "03-zones-and-trust-model.odp"),
    ("04-services-ports-and-protocols.md",           "04-services-ports-and-protocols.odp"),
    ("05-policies-and-inter-zone-routing.md",        "05-policies-and-inter-zone-routing.odp"),
    ("06-rich-rules.md",                             "06-rich-rules.odp"),
    ("07-nat-masquerading-and-port-forwarding.md",   "07-nat-masquerading-and-port-forwarding.odp"),
    ("08-container-integration.md",                  "08-container-integration.odp"),
    ("09-ipsets-and-dynamic-filtering.md",           "09-ipsets-and-dynamic-filtering.odp"),
    ("10-logging-troubleshooting-and-debugging.md",  "10-logging-troubleshooting-and-debugging.odp"),
    ("11-lockdown-mode-and-hardening.md",            "11-lockdown-mode-and-hardening.odp"),
    ("12-direct-rules-and-advanced-nftables.md",     "12-direct-rules-and-advanced-nftables.odp"),
    ("13-capstone-project.md",                       "13-capstone-project.odp"),
]


# ===========================================================================
# Markdown parser
# ===========================================================================

def strip_inline(text: str) -> str:
    """Remove inline markdown formatting."""
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # links
    text = re.sub(r'`([^`]+)`', r'\1', text)              # inline code
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)        # bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)            # italic
    text = re.sub(r'__([^_]+)__', r'\1', text)            # bold alt
    text = re.sub(r'_([^_]+)_', r'\1', text)              # italic alt
    return text.strip()


def is_tree_line(line: str) -> bool:
    """Return True if the line is part of a directory/file tree (├── └── ─── style)."""
    stripped = line.strip()
    return bool(re.match(r'^[├└│\s]*[─]+\s+\S', stripped)) or \
           bool(re.match(r'^[├└│]+', stripped))


def is_table_or_diagram(line: str) -> bool:
    # Directory tree lines are NOT diagrams — handled separately
    if is_tree_line(line):
        return False
    return (line.startswith('|')
            or bool(re.match(r'^[+\-|]+$', line.strip()))
            or bool(re.match(r'^\s*[│├└┌┐┘┤┬┴┼─]+', line))
            or bool(re.match(r'^\s*\+[-+]+', line)))


def is_md_table_block(lines: list) -> bool:
    """Return True if the block looks like a markdown pipe table (has a separator row)."""
    if len(lines) < 2:
        return False
    return bool(re.match(r'^\|[-| :]+\|', lines[1].strip()))


def clean_diag_lines(lines: list) -> str:
    """
    Strip leading/trailing pipe chars from ASCII-diagram lines so LibreOffice
    doesn't interpret them as table-cell borders.
    e.g. '| node1 (gateway) |' → ' node1 (gateway) '
    Lines that are pure box-drawing separators (e.g. '+------+') are kept as-is.
    """
    cleaned = []
    for line in lines:
        # Only strip outer pipes, not box-drawing-only lines
        stripped = re.sub(r'^\|\s?', '', line)
        stripped = re.sub(r'\s?\|$', '', stripped)
        cleaned.append(stripped)
    return '\n'.join(cleaned)


def parse_md_table(lines: list) -> dict:
    """
    Parse a markdown pipe-table block into {'headers': [...], 'rows': [[...], ...]}.
    Strips inline markdown from cell text.
    Skips the separator row (the |---|---| line).
    """
    result = {'headers': [], 'rows': []}
    for i, line in enumerate(lines):
        line = line.strip()
        if not line.startswith('|'):
            continue
        # Separator row — skip
        if re.match(r'^\|[-| :]+\|$', line):
            continue
        cells = [strip_inline(c) for c in line.strip('|').split('|')]
        cells = [c.strip() for c in cells]
        if i == 0:
            result['headers'] = cells
        else:
            result['rows'].append(cells)
    return result


def parse_markdown(md_text: str) -> list:
    """
    Parse a markdown document into a list of slide descriptor dicts.

    Slide dict keys:
      type     : 'title' | 'objectives' | 'content' | 'code' | 'diagram' | 'lab'
      title    : str
      subtitle : str   (title slides only)
      bullets  : list[str]  (up to 8 visible; surplus goes to notes)
      code     : str   (code/diagram slides)
      notes    : str   (full prose for speaker notes)
      is_lab   : bool
    """
    lines = md_text.splitlines()

    # ------------------------------------------------------------------
    # Extract H1 title and > Goal: blockquote
    # ------------------------------------------------------------------
    h1_title = ""
    goal_lines = []
    in_goal = False
    goal_done = False

    for line in lines:
        if line.startswith("# ") and not h1_title:
            h1_title = strip_inline(line[2:].strip())

        if not goal_done:
            if line.startswith("> ") and ("Goal" in line or goal_lines):
                in_goal = True
                goal_lines.append(line[2:].strip())
            elif in_goal and line.startswith(">"):
                goal_lines.append(line[2:].strip() if len(line) > 1 else "")
            elif in_goal:
                goal_done = True

    goal_text = re.sub(r'\*\*Goal:\*\*\s*', '', ' '.join(goal_lines)).strip()

    # ------------------------------------------------------------------
    # Build slide list
    # ------------------------------------------------------------------
    slides = []

    # Slide 1: title
    slides.append({
        'type': 'title',
        'title': h1_title,
        'subtitle': 'Firewalld: Zero to Expert on RHEL 10',
        'bullets': [],
        'code': '',
        'notes': goal_text,
        'is_lab': False,
    })

    # Slide 2: learning objectives (if goal text found)
    if goal_text:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', goal_text) if s.strip()]
        slides.append({
            'type': 'objectives',
            'title': 'Learning Objectives',
            'subtitle': '',
            'bullets': sentences,
            'code': '',
            'notes': goal_text,
            'is_lab': False,
        })

    # ------------------------------------------------------------------
    # Split body by ## headings
    # ------------------------------------------------------------------
    sections = []   # list of (heading_str, body_lines)
    cur_head = None
    cur_body = []

    for line in lines:
        if line.startswith("## "):
            if cur_head is not None:
                sections.append((cur_head, cur_body))
            cur_head = strip_inline(line[3:].strip())
            cur_body = []
        elif not line.startswith("# "):
            if cur_head is not None:
                cur_body.append(line)

    if cur_head is not None:
        sections.append((cur_head, cur_body))

    # ------------------------------------------------------------------
    # Process each ## section
    # ------------------------------------------------------------------
    for heading, body_lines in sections:
        # Skip table of contents
        if re.match(r'^[Tt]able\s+of\s+[Cc]ontents', heading):
            continue

        is_lab = bool(re.match(r'^Lab\s+\d', heading, re.IGNORECASE))

        bullets      = []
        notes_lines  = []
        code_blocks  = []   # list of (lang, text)
        diag_blocks  = []   # list of str
        table_blocks = []   # list of {'headers':[], 'rows':[[],...]}
        tree_bullets = []   # lines from directory-tree blocks, converted to bullets

        in_code   = False
        code_lang = ''
        code_buf  = []
        in_diag   = False
        diag_buf  = []
        in_tree   = False
        tree_buf  = []
        para_buf  = []      # accumulates hard-wrapped paragraph lines
        list_buf  = []      # (indent, prefix, text) — accumulates a list item + continuations

        def flush_para():
            """Emit accumulated paragraph lines as a single bullet."""
            if para_buf:
                # Check if this is a blockquote accumulation
                if para_buf[0].startswith("\x00BQ\x00"):
                    joined = ' '.join(p.replace("\x00BQ\x00", "") for p in para_buf).strip()
                    if joined and "Goal" not in joined:
                        bullets.append("💡 " + joined)
                else:
                    joined = ' '.join(para_buf).strip()
                    if len(joined) > 5:
                        bullets.append(joined)
                para_buf.clear()

        def flush_list():
            """Emit accumulated list item (with its continuation lines) as a single bullet."""
            if list_buf:
                indent_lvl, prefix, parts = list_buf[0][0], list_buf[0][1], []
                for _, _, text in list_buf:
                    parts.append(text)
                joined = ' '.join(parts).strip()
                if joined:
                    bullets.append("  " * indent_lvl + prefix + joined)
                list_buf.clear()

        for line in body_lines:
            # --- Code fences ---
            if line.startswith("```"):
                flush_para(); flush_list()
                if not in_code:
                    in_code = True
                    code_lang = line[3:].strip()
                    code_buf = []
                else:
                    in_code = False
                    code_text = '\n'.join(code_buf)
                    # Admonition-only block? (single line that is just an emoji label)
                    non_empty = [l.strip() for l in code_buf if l.strip()]
                    if (len(non_empty) == 1 and
                            re.match(r'^[\U0001F000-\U0001FFFF⚠️💡📝🔧✅❌→←►◄•◆▸▹✔✗]+\s*\w', non_empty[0])):
                        bullets.append(non_empty[0])
                    # Box-drawing ASCII-art block? Extract text labels as bullets
                    elif not code_lang and re.search(r'[┌┐└┘│─┼┬┴┤├╔╗╚╝║═▼▲►◄]', code_text):
                        seen = set()
                        for raw in code_buf:
                            # Strip all box-drawing chars and surrounding whitespace
                            cleaned = re.sub(r'[┌┐└┘│─┼┬┴┤├╔╗╚╝║═▼▲►◄▶◀\s]+', ' ', raw).strip()
                            # Also strip leftover pipe chars and dashes
                            cleaned = re.sub(r'^[-|+\s]+|[-|+\s]+$', '', cleaned).strip()
                            if cleaned and cleaned not in seen and len(cleaned) > 2:
                                seen.add(cleaned)
                                bullets.append("  ◆ " + cleaned)
                        notes_lines.append(code_text)
                    else:
                        code_blocks.append((code_lang, code_text))
                        notes_lines += ['```' + code_lang] + code_buf + ['```']
                    code_buf = []
                continue

            if in_code:
                code_buf.append(line)
                continue

            # --- Directory trees → bullet list (not diagram) ---
            if is_tree_line(line):
                flush_para(); flush_list()
                if not in_tree:
                    in_tree = True
                    tree_buf = []
                tree_buf.append(line)
                notes_lines.append(line)
                continue
            else:
                if in_tree:
                    in_tree = False
                    for tline in tree_buf:
                        # Strip tree-drawing characters, keep the filename/label
                        clean = re.sub(r'^[│├└─\s]+', '', tline).strip()
                        clean = strip_inline(clean)
                        if clean:
                            tree_bullets.append("  " + clean)
                    tree_buf = []

            # --- Tables / ASCII diagrams ---
            if is_table_or_diagram(line):
                flush_para(); flush_list()
                if not in_diag:
                    in_diag = True
                    diag_buf = []
                diag_buf.append(line)
                notes_lines.append(line)
                continue
            else:
                if in_diag:
                    in_diag = False
                    if len(diag_buf) > 1:
                        if is_md_table_block(diag_buf):
                            table_blocks.append(parse_md_table(diag_buf))
                        else:
                            diag_blocks.append(clean_diag_lines(diag_buf))
                    diag_buf = []

            # --- Horizontal rules ---
            if re.match(r'^[-*_]{3,}\s*$', line.strip()):
                flush_para(); flush_list()
                notes_lines.append(line)
                continue

            # --- H3 sub-headings → bold bullet ---
            if line.startswith("### "):
                flush_para(); flush_list()
                sub = strip_inline(line[4:].strip())
                notes_lines.append(line)
                if sub:
                    bullets.append("◆ " + sub)
                continue

            # --- H4 ---
            if line.startswith("#### "):
                flush_para(); flush_list()
                sub = strip_inline(line[5:].strip())
                notes_lines.append(line)
                if sub:
                    bullets.append("  ▸ " + sub)
                continue

            # --- Blockquotes (tips, concept checks) ---
            if line.startswith("> ") or line == ">":
                content = strip_inline(line[2:].strip()) if line.startswith("> ") else ""
                notes_lines.append(line)
                if content and "Goal" not in content:
                    if para_buf and para_buf[0].startswith("\x00BQ\x00"):
                        # continuation of an existing blockquote
                        para_buf.append("\x00BQ\x00" + content)
                    else:
                        flush_para(); flush_list()
                        para_buf.append("\x00BQ\x00" + content)
                elif not content:
                    flush_para(); flush_list()
                continue

            # --- Unordered list item ---
            m = re.match(r'^(\s*)[-*+]\s+(.*)', line)
            if m:
                flush_para(); flush_list()
                indent = len(m.group(1)) // 2
                content = strip_inline(m.group(2))
                notes_lines.append(line)
                list_buf.append((indent, "• ", content))
                continue

            # --- Ordered list item ---
            m = re.match(r'^(\s*)\d+[.)]\s+(.*)', line)
            if m:
                flush_para(); flush_list()
                indent = len(m.group(1)) // 2
                content = strip_inline(m.group(2))
                notes_lines.append(line)
                list_buf.append((indent, "→ ", content))
                continue

            # --- List continuation line (indented, follows a list item) ---
            if list_buf and re.match(r'^\s{2,}\S', line):
                content = strip_inline(line.strip())
                notes_lines.append(line)
                if content:
                    list_buf.append((list_buf[0][0], "", content))
                continue

            # --- Blank line: flush pending buffers ---
            if not line.strip():
                flush_para(); flush_list()
                notes_lines.append("")
                continue

            # --- Plain paragraph line ---
            plain = strip_inline(line).strip()
            if plain:
                notes_lines.append(line)
                para_buf.append(plain)
            else:
                flush_para(); flush_list()
                notes_lines.append("")

        # Flush trailing paragraph / list item
        flush_para(); flush_list()

        # Flush trailing diagram/table
        if in_diag and len(diag_buf) > 1:
            if is_md_table_block(diag_buf):
                table_blocks.append(parse_md_table(diag_buf))
            else:
                diag_blocks.append(clean_diag_lines(diag_buf))

        # Flush trailing tree block
        if in_tree:
            for tline in tree_buf:
                clean = re.sub(r'^[│├└─\s]+', '', tline).strip()
                clean = strip_inline(clean)
                if clean:
                    tree_bullets.append("  " + clean)

        # Merge tree bullets into main bullet list
        if tree_bullets:
            bullets.extend(tree_bullets)

        notes_text = '\n'.join(notes_lines).strip()

        # Deduplicate bullets
        seen = set()
        deduped = []
        for b in bullets:
            k = b.strip()
            if k and k not in seen:
                seen.add(k)
                deduped.append(b)

        visible  = deduped[:8]
        overflow = deduped[8:]
        if overflow:
            notes_text = '\n'.join(overflow) + '\n\n' + notes_text

        # Main section slide — skip if near-empty and no child slides follow
        has_children = bool(code_blocks or diag_blocks or table_blocks)
        is_near_empty = len(visible) <= 1
        if not (is_near_empty and not has_children):
            slides.append({
                'type':    'lab' if is_lab else 'content',
                'title':   heading,
                'subtitle': '',
                'bullets': visible,
                'code':    '',
                'notes':   notes_text,
                'is_lab':  is_lab,
            })

        # Code slides — merge consecutive same-language blocks that fit in ≤30 lines
        MERGE_LIMIT = 30  # max lines per merged slide
        merged_blocks = []   # list of (lang, combined_text)
        for lang, code_text in code_blocks:
            code_lines = code_text.splitlines()
            if (merged_blocks
                    and merged_blocks[-1][0] == lang
                    and len(merged_blocks[-1][1].splitlines()) + 1 + len(code_lines) <= MERGE_LIMIT):
                # Merge: append a blank separator then the new block
                prev_lang, prev_text = merged_blocks[-1]
                merged_blocks[-1] = (prev_lang, prev_text + '\n\n' + code_text)
            else:
                merged_blocks.append((lang, code_text))

        PAGE = 28  # max lines per code/diagram slide
        for lang, code_text in merged_blocks:
            code_lines = code_text.splitlines()
            label = lang.upper() if lang else 'Code'
            chunks = [code_lines[i:i+PAGE] for i in range(0, len(code_lines), PAGE)]
            for c_idx, chunk in enumerate(chunks):
                suffix = f' (cont. {c_idx + 1})' if c_idx > 0 else ''
                slides.append({
                    'type':    'code',
                    'title':   f'{heading} — {label}{suffix}',
                    'subtitle': '',
                    'bullets': [],
                    'code':    '\n'.join(chunk),
                    'notes':   code_text,   # full text always in notes
                    'is_lab':  is_lab,
                })

        # Diagram / table slides
        for diag in diag_blocks:
            d_lines = diag.splitlines()
            chunks = [d_lines[i:i+PAGE] for i in range(0, len(d_lines), PAGE)]
            for c_idx, chunk in enumerate(chunks):
                suffix = f' (cont. {c_idx + 1})' if c_idx > 0 else ''
                slides.append({
                    'type':    'diagram',
                    'title':   f'{heading} — Reference{suffix}',
                    'subtitle': '',
                    'bullets': [],
                    'code':    '\n'.join(chunk),
                    'notes':   diag,
                    'is_lab':  is_lab,
                })

        # Markdown table slides
        for tbl in table_blocks:
            notes_rows = []
            if tbl['headers']:
                notes_rows.append(' | '.join(tbl['headers']))
                notes_rows.append('-' * 60)
            for row in tbl['rows']:
                notes_rows.append(' | '.join(row))
            slides.append({
                'type':    'table',
                'title':   heading,
                'subtitle': '',
                'bullets': [],
                'code':    '',
                'table':   tbl,
                'notes':   '\n'.join(notes_rows),
                'is_lab':  is_lab,
            })

    return slides


# ===========================================================================
# ODP builder
# ===========================================================================

class Styles:
    """Holds all pre-created style objects for a document."""
    pass


def build_styles(doc) -> Styles:
    """Create and register all styles; return a Styles bag."""
    s = Styles()

    # ---- Page layout ----
    pl = PageLayout(name="Widescreen")
    pl.addElement(PageLayoutProperties(
        pagewidth=SLIDE_W, pageheight=SLIDE_H,
        printorientation="landscape",
        marginleft="0cm", marginright="0cm",
        margintop="0cm", marginbottom="0cm",
    ))
    doc.automaticstyles.addElement(pl)

    # ---- Master page ----
    s.master = MasterPage(name="RHELDark", pagelayoutname="Widescreen")
    doc.masterstyles.addElement(s.master)

    # ---- Drawing-page background styles ----
    def dp_style(name, color):
        st = Style(name=name, family="drawing-page")
        st.addElement(DrawingPageProperties(
            fill="solid", fillcolor=color,
            backgroundobjectsvisible="true",
        ))
        doc.automaticstyles.addElement(st)
        return st

    s.dp_normal = dp_style("dpNormal", C_BG)
    s.dp_lab    = dp_style("dpLab",    C_BG_LAB)
    s.dp_code   = dp_style("dpCode",   C_BG_CODE)

    # ---- Text styles ----
    def ts(name, color, size_pt, bold=False, italic=False,
           font="Liberation Sans"):
        st = Style(name=name, family="text")
        props = dict(color=color, fontsize=f"{size_pt}pt", fontfamily=font)
        if bold:
            props['fontweight'] = 'bold'
        if italic:
            props['fontstyle'] = 'italic'
        st.addElement(TextProperties(**props))
        doc.automaticstyles.addElement(st)
        return st

    s.ts_h1       = ts("tsH1",      C_RED,      36, bold=True)
    s.ts_h1_lab   = ts("tsH1Lab",   C_RED_DARK, 28, bold=True)
    s.ts_subtitle = ts("tsSub",     C_GREY,     22, italic=True)
    s.ts_body     = ts("tsBody",    C_WHITE,    20)
    s.ts_bullet   = ts("tsBullet",  C_WHITE,    18)
    s.ts_obj      = ts("tsObj",     C_WHITE,    20)
    s.ts_code     = ts("tsCode",    C_GREEN,    11, font="DejaVu Sans Mono")
    s.ts_diag     = ts("tsDiag",    C_WHITE,    11, font="DejaVu Sans Mono")
    s.ts_small    = ts("tsSmall",   C_GREY,     14)
    s.ts_lab_b    = ts("tsLabB",    C_WHITE,    18)
    s.ts_lab_step = ts("tsLabStep", C_WHITE,    17)
    # Cache for dynamically-sized code text styles
    s._code_size_cache: dict = {}
    s._doc = doc  # back-reference for lazy style creation

    # ---- Paragraph styles ----
    def ps(name, mt="0.15cm", ml="0cm", lineheight=None):
        st = Style(name=name, family="paragraph")
        kw = dict(margintop=mt, marginleft=ml)
        if lineheight:
            kw['lineheight'] = lineheight
        st.addElement(ParagraphProperties(**kw))
        doc.automaticstyles.addElement(st)
        return st

    s.ps_title  = ps("psTitle",  mt="0.3cm")
    s.ps_sub    = ps("psSub",    mt="0.4cm")
    s.ps_body   = ps("psBody",   mt="0.2cm")
    s.ps_bullet = ps("psBullet", mt="0.12cm", ml="0.4cm")
    s.ps_obj    = ps("psObj",    mt="0.2cm")
    s.ps_code   = ps("psCode",   mt="0cm",    ml="0.1cm", lineheight="110%")
    s.ps_diag   = ps("psDiag",   mt="0cm",               lineheight="110%")
    s.ps_small  = ps("psSmall",  mt="0.15cm")

    # ---- Graphic (frame) styles ----
    def gs(name, fill="none", fillcolor=None, stroke="none",
           pl="0.3cm", pr="0.3cm", pt="0.2cm", pb="0.2cm"):
        st = Style(name=name, family="graphic")
        kw = dict(fill=fill, stroke=stroke,
                  paddingleft=pl, paddingright=pr,
                  paddingtop=pt, paddingbottom=pb)
        if fillcolor:
            kw['fillcolor'] = fillcolor
        st.addElement(GraphicProperties(**kw))
        doc.automaticstyles.addElement(st)
        return st

    s.gs_frame  = gs("gsFrame")
    s.gs_code   = gs("gsCode",  fill="solid", fillcolor=C_BG_CODE,
                     pl="0.5cm", pr="0.5cm", pt="0.4cm", pb="0.4cm")
    # Prevent long code/diagram lines from wrapping — clip overflow and lock size
    _gp_code = s.gs_code.getElementsByType(GraphicProperties)[0]
    _gp_code.setAttrNS(FONS, "overflow-behavior", "clip")
    _gp_code.setAttribute("autogrowheight", "false")
    _gp_code.setAttribute("autogrowwidth",  "false")
    _gp_code.setAttribute("wrap",           "none")
    s.gs_banner = gs("gsBanner", fill="solid", fillcolor=C_RED_DARK,
                     pl="0.6cm", pr="0.6cm", pt="0.3cm", pb="0.3cm")

    # ---- Table cell styles ----
    def tcs(name, bg_color, border_color="#444444"):
        """Create a table-cell style with background and border."""
        st = Style(name=name, family="table-cell")
        cell_props = Element(qname=(STYLENS, "table-cell-properties"))
        cell_props.setAttrNS(FONS, "background-color", bg_color)
        cell_props.setAttrNS(FONS, "border",
                             f"0.05cm solid {border_color}")
        cell_props.setAttrNS(FONS, "padding", "0.18cm")
        st.addElement(cell_props)
        doc.automaticstyles.addElement(st)
        return st

    s.tcs_header = tcs("tcsHeader", C_RED_DARK, C_RED_DARK)
    s.tcs_row_a  = tcs("tcsRowA",  "#252525",  "#444444")
    s.tcs_row_b  = tcs("tcsRowB",  "#1E1E1E",  "#444444")

    # ---- Table column style (width set per-slide via columnwidth attr) ----
    s.tc_col = Style(name="tcCol", family="table-column")
    doc.automaticstyles.addElement(s.tc_col)

    # ---- Text styles for table cells ----
    s.ts_th = ts("tsTh", C_WHITE, 17, bold=True)
    s.ts_td = ts("tsTd", C_WHITE, 16)
    s.ps_cell = ps("psCell", mt="0.05cm")

    return s


# ---------------------------------------------------------------------------
# Dynamic font-size helpers for code / diagram slides
# ---------------------------------------------------------------------------

def font_size_for_code(code_text: str) -> int:
    """
    Choose the largest font size (pt) that keeps the longest line on screen.

    Usable content width ≈ 30.87cm − 1cm padding = 29.87cm ≈ 847pt.
    DejaVu Sans Mono character advance ≈ 0.6 em at 1pt.
    F = 847 / (max_chars * 0.6), clamped to [7, 11].
    """
    lines = code_text.splitlines()
    max_chars = max((len(l) for l in lines), default=40)
    pt = 847.0 / (max(max_chars, 1) * 0.6)
    return max(7, min(11, int(pt)))


def code_text_style(st: Styles, size_pt: int, color: str, font: str) -> object:
    """
    Return (or lazily create) a text Style for the given size/color/font combo.
    Styles are cached on st._code_size_cache to avoid duplicates.
    """
    key = (size_pt, color, font)
    if key in st._code_size_cache:
        return st._code_size_cache[key]

    name = f"tsCodeDyn_{size_pt}_{color.lstrip('#')}_{font.replace(' ', '')}"
    sty = Style(name=name, family="text")
    sty.addElement(TextProperties(
        color=color,
        fontsize=f"{size_pt}pt",
        fontfamily=font,
    ))
    st._doc.automaticstyles.addElement(sty)
    st._code_size_cache[key] = sty
    return sty


def make_frame(style, x, y, w, h):
    """Create a draw:frame at the given position."""
    return Frame(stylename=style, x=x, y=y, width=w, height=h)


def text_para(ts, ps, text: str) -> P:
    """Return a <text:p> containing a styled span."""
    p = P(stylename=ps)
    sp = Span(stylename=ts)
    sp.addText(text)
    p.addElement(sp)
    return p


def add_text_box(slide, style, x, y, w, h, paragraphs: list) -> Frame:
    """
    Add a text-box frame to a slide.
    paragraphs: list of P elements.
    """
    f = make_frame(style, x, y, w, h)
    tb = TextBox()
    for p in paragraphs:
        tb.addElement(p)
    f.addElement(tb)
    slide.addElement(f)
    return f


def add_code_text_box(slide, style, x, y, w, h, code_text: str,
                      ts_style, ps_style) -> Frame:
    """
    Add a code/diagram text-box using a SINGLE text:p with text:line-break
    between lines.  This prevents LibreOffice from treating box-drawing chars
    as table separators and stops per-line paragraph layout artefacts.
    """
    f = make_frame(style, x, y, w, h)
    tb = TextBox()
    p = P(stylename=ps_style)
    lines = code_text.splitlines()
    for i, line in enumerate(lines):
        sp = Span(stylename=ts_style)
        sp.addText(line if line else " ")
        p.addElement(sp)
        if i < len(lines) - 1:
            p.addElement(LineBreak())
    tb.addElement(p)
    f.addElement(tb)
    slide.addElement(f)
    return f


def add_notes(slide, st: Styles, text: str):
    """Attach speaker notes to a slide."""
    if not text.strip():
        return
    notes_el = Notes()
    nf = make_frame(st.gs_frame, x="2cm", y="14cm", w="29cm", h="10cm")
    nf.setAttrNS(PRESENTATIONNS, "class", "notes")
    ntb = TextBox()
    for line in text.splitlines():
        p = P(stylename=st.ps_code)
        sp = Span(stylename=st.ts_diag)
        sp.addText(line if line else " ")
        p.addElement(sp)
        ntb.addElement(p)
    nf.addElement(ntb)
    notes_el.addElement(nf)
    slide.addElement(notes_el)


def new_slide(st: Styles, bg_style):
    """Create a new draw:page with the given background style."""
    return Page(stylename=bg_style, masterpagename="RHELDark")


# ---------------------------------------------------------------------------
# Slide renderers
# ---------------------------------------------------------------------------

def render_title(st: Styles, sd: dict) -> Page:
    slide = new_slide(st, st.dp_normal)

    # Main title
    paras = [text_para(st.ts_h1, st.ps_title, sd['title'])]
    if sd.get('subtitle'):
        paras.append(text_para(st.ts_subtitle, st.ps_sub, sd['subtitle']))
    add_text_box(slide, st.gs_frame,
                 "1.5cm", "4.5cm", "30.87cm", "5cm", paras)

    # Footer
    footer_paras = [
        text_para(st.ts_small, st.ps_small,
                  "Red Hat Enterprise Linux 10  |  Instructor Edition")
    ]
    add_text_box(slide, st.gs_frame,
                 "1.5cm", "17.5cm", "30.87cm", "1cm", footer_paras)

    add_notes(slide, st, sd['notes'])
    return slide


def render_objectives(st: Styles, sd: dict) -> Page:
    slide = new_slide(st, st.dp_normal)

    add_text_box(slide, st.gs_frame,
                 "1.5cm", "0.6cm", "30.87cm", "2cm",
                 [text_para(st.ts_h1, st.ps_title, sd['title'])])

    paras = []
    for b in sd['bullets']:
        if b.strip():
            paras.append(text_para(st.ts_obj, st.ps_obj, "▸  " + b.strip()))
    if paras:
        add_text_box(slide, st.gs_frame,
                     "1.5cm", "3cm", "30.87cm", "15.5cm", paras)

    add_notes(slide, st, sd['notes'])
    return slide


def render_content(st: Styles, sd: dict) -> Page:
    bg = st.dp_lab if sd['is_lab'] else st.dp_normal
    slide = new_slide(st, bg)

    ts_title = st.ts_h1_lab if sd['is_lab'] else st.ts_h1
    add_text_box(slide, st.gs_frame,
                 "1cm", "0.4cm", "31.87cm", "2.2cm",
                 [text_para(ts_title, st.ps_title, sd['title'])])

    paras = []
    for b in sd['bullets']:
        clean = b.strip()
        if clean:
            paras.append(text_para(st.ts_bullet, st.ps_bullet, clean))

    if paras:
        add_text_box(slide, st.gs_frame,
                     "1cm", "2.9cm", "31.87cm", "15.5cm", paras)

    add_notes(slide, st, sd['notes'])
    return slide


def render_lab(st: Styles, sd: dict) -> Page:
    slide = new_slide(st, st.dp_lab)

    # Red banner
    banner_paras = [text_para(st.ts_h1_lab, st.ps_title, "🔧  " + sd['title'])]
    add_text_box(slide, st.gs_banner,
                 "0cm", "0cm", "33.87cm", "2.8cm", banner_paras)

    paras = []
    for b in sd['bullets']:
        clean = b.strip()
        if clean:
            paras.append(text_para(st.ts_lab_step, st.ps_bullet, clean))

    if paras:
        add_text_box(slide, st.gs_frame,
                     "1.5cm", "3.1cm", "30.87cm", "15.5cm", paras)

    add_notes(slide, st, sd['notes'])
    return slide


def render_code(st: Styles, sd: dict) -> Page:
    bg = st.dp_lab if sd['is_lab'] else st.dp_code
    slide = new_slide(st, bg)

    ts_title = st.ts_h1_lab if sd['is_lab'] else st.ts_h1
    add_text_box(slide, st.gs_frame,
                 "1cm", "0.4cm", "31.87cm", "2.6cm",
                 [text_para(ts_title, st.ps_title, sd['title'])])

    if sd['code'].strip():
        size_pt = font_size_for_code(sd['code'])
        ts_dyn  = code_text_style(st, size_pt, C_GREEN, "DejaVu Sans Mono")
        add_code_text_box(slide, st.gs_code,
                          "1cm", "3.3cm", "31.87cm", "15.2cm",
                          sd['code'], ts_dyn, st.ps_code)

    add_notes(slide, st, sd['notes'])
    return slide


def render_diagram(st: Styles, sd: dict) -> Page:
    slide = new_slide(st, st.dp_code)

    add_text_box(slide, st.gs_frame,
                 "1cm", "0.4cm", "31.87cm", "2.6cm",
                 [text_para(st.ts_h1, st.ps_title, sd['title'])])

    if sd['code'].strip():
        size_pt = font_size_for_code(sd['code'])
        ts_dyn  = code_text_style(st, size_pt, C_WHITE, "DejaVu Sans Mono")
        add_code_text_box(slide, st.gs_code,
                          "1cm", "3.3cm", "31.87cm", "15.2cm",
                          sd['code'], ts_dyn, st.ps_diag)

    add_notes(slide, st, sd['notes'])
    return slide


def render_table(st: Styles, sd: dict) -> Page:
    """Render a markdown pipe table as a proper ODF table inside a draw:frame."""
    bg = st.dp_lab if sd['is_lab'] else st.dp_normal
    slide = new_slide(st, bg)

    tbl_data = sd.get('table', {'headers': [], 'rows': []})
    headers  = tbl_data.get('headers', [])
    rows     = tbl_data.get('rows', [])
    n_cols   = max(len(headers), max((len(r) for r in rows), default=0), 1)

    # Title
    ts_title = st.ts_h1_lab if sd['is_lab'] else st.ts_h1
    add_text_box(slide, st.gs_frame,
                 "1cm", "0.4cm", "31.87cm", "2cm",
                 [text_para(ts_title, st.ps_title, sd['title'])])

    # Calculate column widths — distribute 31.87cm evenly, first col slightly wider
    total_w_cm = 31.87
    if n_cols == 1:
        col_widths = [total_w_cm]
    else:
        # Give first column 30% of total, rest split evenly
        first = round(total_w_cm * 0.28, 2)
        rest  = round((total_w_cm - first) / (n_cols - 1), 2)
        col_widths = [first] + [rest] * (n_cols - 1)

    # Frame to hold the table
    tbl_frame = Frame(stylename=st.gs_frame,
                      x="1cm", y="2.8cm", width="31.87cm", height="15.8cm")

    tbl = Table(name="mdtable")

    # Column definitions
    for w in col_widths:
        col_style = Style(name=f"tcCol_{id(tbl)}_{int(w*100)}",
                          family="table-column")
        col_props = Element(qname=(STYLENS, "table-column-properties"))
        col_props.setAttrNS(STYLENS, "column-width", f"{w:.2f}cm")
        col_style.addElement(col_props)
        # Register as automatic style on the document (access via tbl_frame parent later)
        # We embed directly without registration — odfpy will serialise it
        col = TableColumn(stylename=col_style)
        tbl.addElement(col)

    def make_cell(text, cell_style, text_style):
        tc = TableCell(stylename=cell_style)
        p = P(stylename=st.ps_cell)
        sp = Span(stylename=text_style)
        sp.addText(text if text else " ")
        p.addElement(sp)
        tc.addElement(p)
        return tc

    # Header row
    if headers:
        hrow = TableRow()
        for i, h in enumerate(headers):
            cell_text = h if i < len(headers) else ""
            hrow.addElement(make_cell(cell_text, st.tcs_header, st.ts_th))
        # Pad if needed
        for _ in range(n_cols - len(headers)):
            hrow.addElement(make_cell("", st.tcs_header, st.ts_th))
        tbl.addElement(hrow)

    # Data rows
    for r_idx, row in enumerate(rows):
        cell_style = st.tcs_row_a if r_idx % 2 == 0 else st.tcs_row_b
        drow = TableRow()
        for i in range(n_cols):
            cell_text = row[i] if i < len(row) else ""
            drow.addElement(make_cell(cell_text, cell_style, st.ts_td))
        tbl.addElement(drow)

    tbl_frame.addElement(tbl)
    slide.addElement(tbl_frame)

    add_notes(slide, st, sd['notes'])
    return slide


RENDERERS = {
    'title':      render_title,
    'objectives': render_objectives,
    'content':    render_content,
    'lab':        render_lab,
    'code':       render_code,
    'diagram':    render_diagram,
    'table':      render_table,
}


def build_odp(slides_data: list, output_path: Path):
    doc = OpenDocumentPresentation()
    st  = build_styles(doc)

    for sd in slides_data:
        renderer = RENDERERS.get(sd['type'], render_content)
        slide = renderer(st, sd)
        doc.presentation.addElement(slide)

    doc.save(str(output_path))


# ===========================================================================
# Main
# ===========================================================================

def main():
    SLIDES_DIR.mkdir(exist_ok=True)
    total = 0

    for src_name, out_name in SOURCE_FILES:
        src_path = COURSE_DIR / src_name
        out_path = SLIDES_DIR / out_name

        if not src_path.exists():
            print(f"  SKIP  {src_name}")
            continue

        print(f"  {src_name}  →  slides/{out_name}", end="  ", flush=True)
        md_text    = src_path.read_text(encoding="utf-8")
        slides_data = parse_markdown(md_text)
        build_odp(slides_data, out_path)
        size_kb = out_path.stat().st_size // 1024
        print(f"[{len(slides_data)} slides, {size_kb} KB]")
        total += 1

    print(f"\n✓  {total} decks written to slides/")


if __name__ == "__main__":
    main()

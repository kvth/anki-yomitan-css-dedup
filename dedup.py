"""Core logic: move repeated Yomitan stylesheets out of note fields into the note type.

Yomitan copies each dictionary's stylesheet as a <style> block into every note.
For a note type this module moves those blocks into the note type's styling and
removes them from the fields:

- Stylesheets of a dictionary (they contain `data-dictionary="..."`) are kept
  once per dictionary; the version used by the most notes wins, newest on a tie.
- Any other <style> block is only merged with exact copies of itself.
- They are appended at the end of the note type CSS, which is the same cascade
  position they had inside the card.

Everything else in the fields stays unchanged. Running it again is a no-op until
new notes bring new <style> blocks.

This module only depends on the `anki` collection API, not on the GUI, so it is
shared by the add-on (`__init__.py`) and the command line tool (`cli.py`).
"""

from __future__ import annotations

import hashlib
import html
import re
from collections import Counter
from dataclasses import dataclass, field

SHEETS_BEGIN = "/* BEGIN yomitan-dictionary-styles (generated, do not edit) */"
SHEETS_END = "/* END yomitan-dictionary-styles */"
SHEET_HEADER = "/* yomitan-sheet: {} */"

STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
SHEET_RE = re.compile(r"/\* yomitan-sheet: (.*?) \*/\n(.*?)(?=\n/\* yomitan-sheet: |\Z)", re.S)
DICT_RE = re.compile(r'data-dictionary="([^"]+)"')


def get_section(css: str) -> str:
    s, e = css.find(SHEETS_BEGIN), css.find(SHEETS_END)
    return css[s + len(SHEETS_BEGIN):e].strip("\n") if s != -1 and e != -1 else ""


def set_section(css: str, body: str) -> str:
    block = f"{SHEETS_BEGIN}\n{body}\n{SHEETS_END}" if body.strip() else ""
    s, e = css.find(SHEETS_BEGIN), css.find(SHEETS_END)
    if s != -1 and e != -1:
        return css[:s] + block + css[e + len(SHEETS_END):]
    return css.rstrip() + "\n\n" + block + "\n" if block else css


def sheet_key(sheet_css: str) -> str:
    """Group a stylesheet belongs to.

    Stylesheets of a Yomitan dictionary are grouped by the dictionary name, so
    only one version per dictionary is kept. Any other stylesheet is its own
    group (keyed by its content), so only exact copies are merged.
    """
    m = DICT_RE.search(sheet_css)
    if m:
        return html.unescape(m.group(1))
    return "sha1:" + hashlib.sha1(sheet_css.encode()).hexdigest()[:12]


@dataclass
class Plan:
    notetype: dict
    changed_notes: list = field(default_factory=list)
    new_css: str = ""
    notes_total: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    sheets: int = 0
    css_growth: int = 0

    @property
    def saved_bytes(self) -> int:
        return self.bytes_before - self.bytes_after

    @property
    def css_changed(self) -> bool:
        return self.new_css != self.notetype["css"]

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_notes) or self.css_changed

    def extracted_css(self) -> str:
        """The generated CSS section, e.g. to keep a copy outside the collection."""
        return get_section(self.new_css) + "\n"

    def summary(self) -> str:
        return (f"{self.notetype['name']}: {len(self.changed_notes)} of {self.notes_total} notes change, "
                f"note fields {self.bytes_before / 1e6:.1f} MB -> {self.bytes_after / 1e6:.1f} MB "
                f"(-{self.saved_bytes / 1e6:.1f} MB); "
                f"{self.sheets} stylesheets in the note type CSS (+{self.css_growth / 1e3:.0f} KB)")


def plan_notetype(col, notetype: dict) -> Plan:
    """Compute the changes for one note type without writing anything."""
    notes = [col.get_note(nid) for nid in col.models.nids(notetype)]
    notes.sort(key=lambda n: n.mod)  # oldest first, so newer sheets win ties
    css = notetype["css"]

    sheets = dict(SHEET_RE.findall(get_section(css)))
    sheet_counts: Counter = Counter()  # (group, sheet) -> notes using it
    plan = Plan(notetype=notetype, notes_total=len(notes))
    for note in notes:
        dirty = False
        for i, old in enumerate(note.fields):
            for sheet in STYLE_BLOCK_RE.findall(old):
                key = sheet_key(sheet)
                sheet_counts[key, sheet] += 1
                if sheet_counts[key, sheet] >= sheet_counts.get((key, sheets.get(key)), 0):
                    sheets[key] = sheet
            new = STYLE_BLOCK_RE.sub("", old)
            plan.bytes_before += len(old.encode())
            plan.bytes_after += len(new.encode())
            if new != old:
                note.fields[i] = new
                dirty = True
        if dirty:
            plan.changed_notes.append(note)

    sheets_body = "\n".join(SHEET_HEADER.format(k) + "\n" + v for k, v in sheets.items())
    plan.new_css = set_section(css, sheets_body)
    plan.sheets = len(sheets)
    plan.css_growth = len(plan.new_css.encode()) - len(css.encode())
    return plan


def apply_plan(col, plan: Plan) -> None:
    """Write a plan: CSS first, so the styling is in place before the notes lose it."""
    if plan.css_changed:
        plan.notetype["css"] = plan.new_css
        col.models.update_dict(plan.notetype)
    if plan.changed_notes:
        col.update_notes(plan.changed_notes)

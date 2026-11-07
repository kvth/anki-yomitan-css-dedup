"""Core logic: move repeated Yomitan stylesheets out of note fields into the note type.

Yomitan copies each dictionary's stylesheet as a <style> block into every note.
For a note type this module moves the rules that are limited to one dictionary
(every selector contains `[data-dictionary="..."]`) into the note type's styling:

- They are kept once per dictionary; the version used by the most notes wins,
  newest on a tie.
- They are appended at the end of the note type CSS, which is the same cascade
  position they had inside the card.
- All other rules (e.g. Yomitan's compact glossary rules, which match every
  glossary on a card) stay in the note as a small <style> block, so they keep
  reaching exactly the notes they reached before. Blocks without any rule
  limited to a dictionary are left untouched.

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

STYLE_BLOCK_RE = re.compile(r"(<style[^>]*>)(.*?)(</style>)", re.S)
SHEET_RE = re.compile(r"/\* yomitan-sheet: (.*?) \*/\n(.*?)(?=\n/\* yomitan-sheet: |\Z)", re.S)
DICT_RE = re.compile(r'data-dictionary="([^"]+)"')
COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def get_section(css: str) -> str:
    s, e = css.find(SHEETS_BEGIN), css.find(SHEETS_END)
    return css[s + len(SHEETS_BEGIN):e].strip("\n") if s != -1 and e != -1 else ""


def set_section(css: str, body: str) -> str:
    block = f"{SHEETS_BEGIN}\n{body}\n{SHEETS_END}" if body.strip() else ""
    s, e = css.find(SHEETS_BEGIN), css.find(SHEETS_END)
    if s != -1 and e != -1:
        return css[:s] + block + css[e + len(SHEETS_END):]
    return css.rstrip() + "\n\n" + block + "\n" if block else css


def style_blocks(text: str) -> list[str]:
    """Contents of the <style> blocks in a field."""
    return [m.group(2) for m in STYLE_BLOCK_RE.finditer(text)]


def without_style_blocks(text: str) -> str:
    return STYLE_BLOCK_RE.sub("", text)


def sheet_key(sheet_css: str) -> str:
    """Dictionary a moved stylesheet belongs to; only one version per key is kept."""
    m = DICT_RE.search(sheet_css)
    if m:
        return html.unescape(m.group(1))
    return "sha1:" + hashlib.sha1(sheet_css.encode()).hexdigest()[:12]


# --- CSS parsing ----------------------------------------------------------------------

@dataclass(frozen=True)
class Chunk:
    """A top-level piece of a stylesheet: a rule, or anything else (statement, junk)."""
    raw: str
    selector: str | None = None
    body: str | None = None


def top_level_chunks(css: str) -> list[Chunk]:
    css = COMMENT_RE.sub("", css)
    chunks, depth, start, body_start, quote, selector = [], 0, 0, 0, None, ""
    for i, ch in enumerate(css):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            if depth == 0:
                selector, body_start = css[start:i].strip(), i + 1
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                chunks.append(Chunk(css[start:i + 1].strip(), selector, css[body_start:i]))
                start = i + 1
        elif ch == ";" and depth == 0:
            if css[start:i].strip():
                chunks.append(Chunk(css[start:i + 1].strip()))
            start = i + 1
    if css[start:].strip():
        chunks.append(Chunk(css[start:].strip()))
    return chunks


def is_valid_selector(selector: str) -> bool:
    """False for selectors browsers drop, like those broken by Yomitan's stray <br>."""
    quote = None
    for ch in selector:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "<":
            return False
    return bool(selector)


def is_dictionary_scoped(chunk: Chunk) -> bool:
    """True if the rule can only ever match inside entries of one dictionary."""
    if chunk.selector is None or not is_valid_selector(chunk.selector):
        return False
    if chunk.selector.startswith("@"):  # @media etc.: scoped if everything inside is
        inner = top_level_chunks(chunk.body)
        return bool(inner) and all(is_dictionary_scoped(c) for c in inner)
    return bool(make_rule(chunk.selector, chunk.body).dictionaries)


def split_sheet(css: str) -> tuple[str, list[str]]:
    """Split a stylesheet into the rules limited to a dictionary (to move) and the rest."""
    scoped, rest = [], []
    for chunk in top_level_chunks(css):
        (scoped if is_dictionary_scoped(chunk) else rest).append(chunk.raw)
    return "\n".join(scoped), rest


# --- render check ---------------------------------------------------------------------
#
# Moving CSS leaves the text and markup of a card untouched, so a card can only
# look different if the set of CSS rules that can apply to it changes: its own
# stylesheet version was not the one kept, or rules from other stylesheets now
# reach it. The check compares, per note, the rules that could match it before
# and after.

CLASS_ATTR_RE = re.compile(r'\sclass="([^"]*)"')
SELECTOR_CLASS_RE = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
NEGATING_PSEUDO_RE = re.compile(r":(?:not|is|where)\((?:[^()]|\([^()]*\))*\)")
# Classes Anki itself puts on the card's <html>/<body>.
ANKI_CLASSES = {"card", "nightMode", "night_mode", "mobile", "android", "iphone", "ipad",
                "linux", "mac", "win", "isMac", "isWin", "isLin"}


@dataclass(frozen=True)
class Rule:
    selector: str
    body: str
    classes: frozenset  # all of these must exist for the rule to match
    dictionaries: frozenset  # the note must contain entries of all of these

    @property
    def scope(self) -> str:
        return next(iter(self.dictionaries)) if len(self.dictionaries) == 1 else ""


def parse_rules(css: str) -> list[Rule]:
    """Top-level rules of a stylesheet that browsers would use."""
    return [make_rule(c.selector, normalize_body(c.body)) for c in top_level_chunks(css)
            if c.selector is not None and is_valid_selector(c.selector)]


def normalize_body(body: str) -> str:
    """Declarations as a browser keeps them: whitespace collapsed, invalid
    declarations (like Yomitan's stray `<br>`) dropped."""
    body = " ".join(body.split())
    if "{" in body:  # nested rules: compare as text
        return body
    decls = [d.strip() for d in body.split(";")]
    return "; ".join(d for d in decls if d and "<" not in d and ":" in d)


def make_rule(selector: str, body: str) -> Rule:
    if selector.startswith("@"):
        inner = {html.unescape(d) for d in DICT_RE.findall(body)}
        return Rule(selector, body, frozenset(), frozenset(inner) if len(inner) == 1 else frozenset())
    parts = [NEGATING_PSEUDO_RE.sub("", p) for p in split_selector_list(selector)]
    # A selector list matches if any part does, so only requirements of all parts count.
    classes = set.intersection(*(set(SELECTOR_CLASS_RE.findall(p)) for p in parts))
    dicts = set.intersection(*({html.unescape(d) for d in DICT_RE.findall(p)} for p in parts))
    return Rule(selector, body, frozenset(classes), frozenset(dicts))


def split_selector_list(selector: str) -> list[str]:
    parts, depth, buf = [], 0, []
    for ch in selector:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()] or [selector]


@dataclass
class RenderCheck:
    """Notes that could render differently, by stylesheet scope."""
    notes_affected: int = 0
    # scope ('' = rules not limited to one dictionary) -> notes affected, differing rules
    notes_by_scope: Counter = field(default_factory=Counter)
    rules_by_scope: dict = field(default_factory=dict)

    @property
    def identical(self) -> bool:
        return self.notes_affected == 0

    def report(self) -> str:
        if self.identical:
            return "Render check: all cards keep exactly the same CSS rules."
        lines = [f"Render check: {self.notes_affected} notes could look slightly different:"]
        for scope, n in sorted(self.notes_by_scope.items(), key=lambda x: (x[0] != "", -x[1])):
            rules = self.rules_by_scope[scope]
            if scope:
                lines.append(f"- {scope}: {n} notes, {len(rules)} rules differ "
                             f"(other version of its stylesheet, or entries without it)")
            else:
                example = min(rules, key=len)
                lines.append(f"- Rules not limited to one dictionary: {n} notes, {len(rules)} rules differ, "
                             f"e.g. {example[:80]}")
        return "\n".join(lines)


class RenderChecker:
    def __init__(self, notetype: dict, old_sheets: list[str]):
        templates = " ".join(t.get("qfmt", "") + t.get("afmt", "") for t in notetype.get("tmpls", []))
        # Anything that looks like a word in the templates might be a class.
        self.template_classes = set(re.findall(r"[\w-]+", templates)) | ANKI_CLASSES
        self.rule_cache: dict = {}
        self.old_rules = self.rules_of(old_sheets)
        self.notes: list = []  # (sheets before, sheets left in the note, classes, dictionaries)

    def rules_of(self, sheets) -> set:
        out = set()
        for s in sheets:
            if s not in self.rule_cache:
                self.rule_cache[s] = frozenset(parse_rules(s))
            out |= self.rule_cache[s]
        return out

    def add_note(self, sheets_before: list[str], sheets_after: list[str], fields: list[str]) -> None:
        text = "\n".join(without_style_blocks(f) for f in fields)
        classes = {c for attr in CLASS_ATTR_RE.findall(text) for c in attr.split()}
        dicts = {html.unescape(d) for d in DICT_RE.findall(text)}
        self.notes.append((tuple(sheets_before), tuple(sheets_after), frozenset(classes), frozenset(dicts)))

    def check(self, new_sheets: list[str]) -> RenderCheck:
        new_rules = self.rules_of(new_sheets)
        result = RenderCheck()
        for before_sheets, after_sheets, classes, dicts in self.notes:
            known = classes | self.template_classes

            def applies(rule: Rule) -> bool:
                return rule.dictionaries <= dicts and rule.classes <= known

            before = {r for r in self.old_rules | self.rules_of(before_sheets) if applies(r)}
            after = {r for r in new_rules | self.rules_of(after_sheets) if applies(r)}
            diff = before ^ after
            if not diff:
                continue
            result.notes_affected += 1
            for scope in {r.scope for r in diff}:
                result.notes_by_scope[scope] += 1
            for r in diff:
                result.rules_by_scope.setdefault(r.scope, set()).add(r.selector)
        return result


# --- planning and applying ------------------------------------------------------------

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
    check: RenderCheck = field(default_factory=RenderCheck)

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


def process_field(text: str, split) -> tuple[str, list[str]]:
    """Take the dictionary-scoped rules out of a field's <style> blocks.

    Returns the new field text and the moved stylesheets. A block keeps its
    other rules (each distinct rule once per field); a block without any rule
    limited to a dictionary is left exactly as it is.
    """
    moved, kept_rules = [], set()

    def repl(m):
        scoped, rest = split(m.group(2))
        if not scoped:
            return m.group(0)
        moved.append(scoped)
        rest = [r for r in rest if " ".join(r.split()) not in kept_rules]
        kept_rules.update(" ".join(r.split()) for r in rest)
        return f"{m.group(1)}{chr(10).join(rest)}{m.group(3)}" if rest else ""

    return STYLE_BLOCK_RE.sub(repl, text), moved


def plan_notetype(col, notetype: dict) -> Plan:
    """Compute the changes for one note type without writing anything."""
    notes = [col.get_note(nid) for nid in col.models.nids(notetype)]
    notes.sort(key=lambda n: n.mod)  # oldest first, so newer sheets win ties
    css = notetype["css"]

    sheets = dict(SHEET_RE.findall(get_section(css)))
    checker = RenderChecker(notetype, list(sheets.values()))
    canonical: dict = {}  # one string object per distinct sheet, to save memory
    split_cache: dict = {}

    def intern(s: str) -> str:
        return canonical.setdefault(s, s)

    def split(css_text: str):
        if css_text not in split_cache:
            scoped, rest = split_sheet(css_text)
            split_cache[css_text] = (intern(scoped), rest)
        return split_cache[css_text]

    sheet_counts: Counter = Counter()  # (dictionary, sheet) -> notes using it
    plan = Plan(notetype=notetype, notes_total=len(notes))
    for note in notes:
        dirty = False
        before, after = [], []
        for i, old in enumerate(note.fields):
            before += [intern(s) for s in style_blocks(old)]
            new, moved = process_field(old, split)
            for sheet in moved:
                key = sheet_key(sheet)
                sheet_counts[key, sheet] += 1
                if sheet_counts[key, sheet] >= sheet_counts.get((key, sheets.get(key)), 0):
                    sheets[key] = sheet
            after += [intern(s) for s in style_blocks(new)]
            plan.bytes_before += len(old.encode())
            plan.bytes_after += len(new.encode())
            if new != old:
                note.fields[i] = new
                dirty = True
        if dirty:
            plan.changed_notes.append(note)
        checker.add_note(before, after, note.fields)

    sheets_body = "\n".join(SHEET_HEADER.format(k) + "\n" + v for k, v in sheets.items())
    plan.new_css = set_section(css, sheets_body)
    plan.sheets = len(sheets)
    plan.css_growth = len(plan.new_css.encode()) - len(css.encode())
    plan.check = checker.check(list(sheets.values()))
    return plan


def apply_plan(col, plan: Plan) -> None:
    """Write a plan: CSS first, so the styling is in place before the notes lose it."""
    if plan.css_changed:
        plan.notetype["css"] = plan.new_css
        col.models.update_dict(plan.notetype)
    if plan.changed_notes:
        col.update_notes(plan.changed_notes)

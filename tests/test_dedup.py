"""Tests for dedup.py. Run: python -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dedup  # noqa: E402

SHEET_A1 = '.yomitan-glossary [data-dictionary="A"] b { color: red; }'
SHEET_A2 = '.yomitan-glossary [data-dictionary="A"] b { color: blue; }'
SHEET_B = '.yomitan-glossary [data-dictionary="B"] i { margin: 0; }'


class FakeNote:
    def __init__(self, nid, fields, mod):
        self.id, self.fields, self.mod = nid, list(fields), mod


class FakeModels:
    def __init__(self, col):
        self.col = col

    def nids(self, notetype):
        return list(self.col.notes)

    def update_dict(self, notetype):
        self.col.css = notetype["css"]


class FakeCollection:
    def __init__(self, fields_per_note, css="body { margin: 0; }"):
        self.notes = {i: (list(f), i) for i, f in enumerate(fields_per_note)}
        self.css = css
        self.models = FakeModels(self)

    def notetype(self):
        return {"name": "Yomitan", "css": self.css}

    def get_note(self, nid):
        fields, mod = self.notes[nid]
        return FakeNote(nid, fields, mod)

    def update_notes(self, notes):
        for n in notes:
            self.notes[n.id] = (list(n.fields), n.mod)


def run(col):
    plan = dedup.plan_notetype(col, col.notetype())
    dedup.apply_plan(col, plan)
    return plan


class StyleBlockTests(unittest.TestCase):
    def test_blocks_move_to_end_of_css_and_leave_fields(self):
        col = FakeCollection([[f"<style>{SHEET_A1}</style><div>text</div>", "x"]])
        run(col)
        self.assertEqual(col.notes[0][0], ["<div>text</div>", "x"])
        self.assertTrue(col.css.startswith("body { margin: 0; }"))
        self.assertIn(SHEET_A1, col.css)
        self.assertGreater(col.css.index(SHEET_A1), col.css.index("body"))

    def test_most_used_version_wins(self):
        col = FakeCollection([[f"<style>{SHEET_A1}</style>"]] * 3 + [[f"<style>{SHEET_A2}</style>"]])
        run(col)
        self.assertIn(SHEET_A1, col.css)
        self.assertNotIn(SHEET_A2, col.css)

    def test_one_sheet_per_dictionary(self):
        col = FakeCollection([[f"<style>{SHEET_A1}</style><style>{SHEET_B}</style>"],
                              [f"<style>{SHEET_B}</style>"]])
        plan = run(col)
        self.assertEqual(plan.sheets, 2)
        self.assertEqual(col.css.count(SHEET_B), 1)

    def test_blocks_without_dictionary_only_merge_exact_copies(self):
        plain1, plain2 = "b { color: red; }", "i { color: blue; }"
        col = FakeCollection([[f"<style>{plain1}</style>"], [f"<style>{plain1}</style>"],
                              [f"<style>{plain2}</style>"]])
        plan = run(col)
        self.assertEqual(plan.sheets, 2)
        self.assertEqual(col.css.count(plain1), 1)
        self.assertEqual(col.css.count(plain2), 1)

    def test_rerun_is_noop_and_keeps_sheets(self):
        col = FakeCollection([[f"<style>{SHEET_A1}</style><span style=\"color:red\">a</span>"]] * 3)
        run(col)
        css_after_first = col.css
        plan = run(col)
        self.assertFalse(plan.has_changes)
        self.assertEqual(col.css, css_after_first)

    def test_new_notes_after_rerun_are_cleaned(self):
        col = FakeCollection([[f"<style>{SHEET_A1}</style>"]])
        run(col)
        col.notes[1] = ([f"<style>{SHEET_A1}</style><p>new</p>"], 1)
        run(col)
        self.assertEqual(col.notes[1][0], ["<p>new</p>"])
        self.assertEqual(col.css.count(SHEET_A1), 1)


class UntouchedTests(unittest.TestCase):
    def test_inline_styles_and_attributes_stay(self):
        html = '<div data-sc-content="x" class="a" style="color:red" lang="ja">t</div>'
        col = FakeCollection([[f"<style>{SHEET_A1}</style>{html}"]] * 3)
        run(col)
        self.assertEqual(col.notes[0][0], [html])

    def test_notes_without_style_blocks_unchanged(self):
        col = FakeCollection([["<b>plain</b>", ""]])
        plan = run(col)
        self.assertFalse(plan.has_changes)
        self.assertEqual(col.css, "body { margin: 0; }")


if __name__ == "__main__":
    unittest.main()

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

    def test_blocks_without_dictionary_stay_untouched(self):
        plain = "<style>b { color: red; }</style>"
        col = FakeCollection([[plain + "<b>x</b>"]] * 2)
        plan = run(col)
        self.assertFalse(plan.has_changes)
        self.assertEqual(col.notes[0][0], [plain + "<b>x</b>"])

    def test_rules_not_limited_to_a_dictionary_stay_in_their_notes(self):
        sheet_a = SHEET_A1 + "\n" + COMPACT
        col = FakeCollection([[f"<style>{sheet_a}</style>{ENTRY_A}"],
                              [f"<style>{SHEET_B}</style>{ENTRY_B}"]])
        plan = run(col)
        self.assertEqual(col.notes[0][0], [f"<style>{COMPACT}</style>{ENTRY_A}"])
        self.assertEqual(col.notes[1][0], [ENTRY_B])
        self.assertNotIn("display: inline", col.css)
        self.assertTrue(plan.check.identical, plan.check.report())

    def test_kept_rules_appear_once_per_field(self):
        sheet_a, sheet_b = SHEET_A1 + "\n" + COMPACT, SHEET_B + "\n" + COMPACT
        col = FakeCollection([[f"<style>{sheet_a}</style><style>{sheet_b}</style>{ENTRY_A}{ENTRY_B}"]])
        run(col)
        self.assertEqual(col.notes[0][0], [f"<style>{COMPACT}</style>{ENTRY_A}{ENTRY_B}"])

    def test_at_rule_moves_only_if_everything_inside_is_scoped(self):
        scoped = '@media (max-width: 600px) { .yomitan-glossary [data-dictionary="A"] b { color: red; } }'
        mixed = '@media print { .yomitan-glossary [data-dictionary="A"] b { color: red; } ul { margin: 0; } }'
        moved, rest = dedup.split_sheet(scoped + "\n" + mixed)
        self.assertEqual(moved, scoped)
        self.assertEqual(rest, [mixed])

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


COMPACT = '.yomitan-glossary ul[data-sc-content="glossary"] { display: inline; }'
ENTRY_A = '<div class="yomitan-glossary"><ol><li data-dictionary="A"><ul data-sc-content="glossary"><li>x</li></ul></li></ol></div>'
ENTRY_B = ENTRY_A.replace('"A"', '"B"')


class RenderCheckTests(unittest.TestCase):
    def check(self, fields_per_note):
        col = FakeCollection(fields_per_note)
        return dedup.plan_notetype(col, col.notetype()).check

    def test_same_sheet_everywhere_is_identical(self):
        result = self.check([[f"<style>{SHEET_A1}</style>{ENTRY_A}"]] * 3)
        self.assertTrue(result.identical, result.report())

    def test_other_version_is_reported_for_its_dictionary(self):
        result = self.check([[f"<style>{SHEET_A1}</style>{ENTRY_A}"]] * 2
                            + [[f"<style>{SHEET_A2}</style>{ENTRY_A}"]])
        self.assertEqual(result.notes_affected, 1)
        self.assertEqual(result.notes_by_scope["A"], 1)

    def test_global_rules_removed_from_note_type_css_are_reported(self):
        # An earlier version moved a global rule into the note type CSS; replacing
        # that sheet with a scoped-only version takes the rule away from all notes.
        old_section = dedup.SHEET_HEADER.format("A") + "\n" + SHEET_A2 + "\n" + COMPACT
        col = FakeCollection([[f"<style>{SHEET_A1}</style>{ENTRY_A}"]],
                             css=dedup.set_section("body { margin: 0; }", old_section))
        result = dedup.plan_notetype(col, col.notetype()).check
        self.assertEqual(result.notes_by_scope[""], 1)
        self.assertIn("Rules not limited to one dictionary", result.report())

    def test_rule_needing_a_missing_class_does_not_count(self):
        sheet_a = SHEET_A1 + "\n" + COMPACT
        result = self.check([[f"<style>{sheet_a}</style>{ENTRY_A}"],
                             [f"<style>{SHEET_B}</style><p>no glossary here</p>"]])
        self.assertTrue(result.identical, result.report())

    def test_entries_without_their_sheet_are_reported(self):
        result = self.check([[f"<style>{SHEET_A1}</style>{ENTRY_A}"], [ENTRY_A]])
        self.assertEqual(result.notes_by_scope["A"], 1)

    def test_stray_br_in_declarations_is_ignored(self):
        broken = SHEET_A1.replace("color: red;", "color: red;<br>")
        result = self.check([[f"<style>{SHEET_A1}</style>{ENTRY_A}"]] * 2
                            + [[f"<style>{broken}</style>{ENTRY_A}"]])
        self.assertTrue(result.identical, result.report())

    def test_rerun_is_identical(self):
        col = FakeCollection([[f"<style>{SHEET_A1}</style>{ENTRY_A}"],
                              [f"<style>{SHEET_A2}</style>{ENTRY_A}"]])
        run(col)
        self.assertTrue(dedup.plan_notetype(col, col.notetype()).check.identical)

    def test_selector_broken_by_br_never_applies(self):
        self.assertEqual(dedup.parse_rules("<br>.a b { color: red; } .c { margin: 0; }"),
                         [dedup.make_rule(".c", "margin: 0")])


if __name__ == "__main__":
    unittest.main()

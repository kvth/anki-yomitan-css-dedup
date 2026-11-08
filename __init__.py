"""Yomitan CSS Dedup: Anki add-on entry point (Tools → Yomitan CSS Dedup)."""

from __future__ import annotations

import copy
import re
from pathlib import Path

import aqt
from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import QAction, QMenu
from aqt.utils import askUser, showInfo, tooltip

from .config_dialog import ConfigDialog
from .dedup import apply_plan, note_type_stats, plan_notetype, without_style_blocks
from .summary_dialog import SummaryDialog
from .visual import VisualComparer

ADDON_DIR = Path(__file__).parent
ADDON_NAME = "Yomitan CSS Dedup"
TAG_CHANGED = "yomitan-css-dedup::changed"  # look different (visual comparison)
TAG_CHECK = "yomitan-css-dedup::check"  # could look different (render check only)


def get_config() -> dict:
    config = mw.addonManager.getConfig(__name__) or {}
    return {
        "note_types": list(config.get("note_types", ["Yomitan"])),
        "backup_before_apply": bool(config.get("backup_before_apply", True)),
        "tag_changed_notes": bool(config.get("tag_changed_notes", True)),
    }


def plan_all(col, config: dict) -> tuple[list, list[str]]:
    plans, missing = [], []
    for name in config["note_types"]:
        notetype = col.models.by_name(name)
        if notetype is None:
            missing.append(name)
            continue
        plans.append(plan_notetype(col, notetype))
    return plans, missing


def save_css_copies(plans: list) -> None:
    """Keep the extracted CSS in user_files/, which survives add-on updates."""
    out_dir = ADDON_DIR / "user_files"
    out_dir.mkdir(exist_ok=True)
    for plan in plans:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in plan.notetype["name"])
        (out_dir / f"{safe_name}.css").write_text(plan.extracted_css(), encoding="utf-8")


def open_browser(search: str) -> None:
    aqt.dialogs.open("Browser", mw, search=(search,))


def show_notes(nids: list) -> None:
    if nids:
        open_browser("nid:" + ",".join(str(n) for n in nids))


def note_label(col, nid: int) -> str:
    note = col.get_note(nid)
    text = re.sub(r"<[^>]+>", "", without_style_blocks(note.fields[note.note_type()["sortf"]]))
    return text.strip()[:40] or str(nid)


def on_planned(result: tuple[list, list[str]], config: dict) -> None:
    plans, missing = result
    lines = [f"{p.summary()}\n\n{p.check.report()}" for p in plans]
    if missing:
        lines.append(f"Note types not found: {', '.join(missing)}.")
    plans = [p for p in plans if p.has_changes]
    if not plans:
        if askUser("Nothing to do.\n\n" + "\n\n".join(lines)
                   + "\n\nOpen the settings to choose other note types?",
                   parent=mw, title=ADDON_NAME, defaultno=True):
            on_settings()
        return

    candidates = [nid for p in plans for nid in p.check.affected]
    state: dict = {"visual": None}

    def compare() -> None:
        def done(results: dict, cancelled: bool) -> None:
            state["visual"] = None if cancelled else results
            rows = [(nid, note_label(mw.col, nid), f"{count} elements, e.g. {samples[0][:90]}")
                    for nid, (count, samples) in results.items()]
            dialog.set_results(rows, cancelled)

        compare_visually(plans, candidates, dialog, done)

    def apply() -> None:
        dialog.accept()
        apply_changes(config, state["visual"])

    dialog = SummaryDialog(mw, "\n\n".join(lines), len(candidates), not candidates,
                           on_compare=compare, on_show=show_notes, on_apply=apply)
    dialog.candidate_nids = candidates
    dialog.show()


def compare_visually(plans: list, nids: list, parent, done) -> None:
    """Render every listed note before and after; done(results, cancelled)."""
    by_nid = {}
    for plan in plans:
        changed = {n.id: n for n in plan.changed_notes}
        notetype_after = copy.deepcopy(plan.notetype)
        notetype_after["css"] = plan.new_css
        for nid in plan.check.affected:
            by_nid[nid] = (changed, notetype_after)

    def render(nid):
        changed, notetype_after = by_nid[nid]
        note = mw.col.get_note(nid)
        cards = note.cards()
        if not cards:
            return None
        after = changed.get(nid, note).ephemeral_card(cards[0].ord, custom_note_type=notetype_after)
        return cards[0].answer(), after.answer(), cards[0].ord

    cancelled = False

    def progress(i: int, total: int) -> bool:
        nonlocal cancelled
        mw.progress.update(label=f"Comparing cards visually… {i:,} / {total:,} (Esc to cancel)",
                           value=i, max=total)
        cancelled = mw.progress.want_cancel()
        return not cancelled

    def finished(results: dict) -> None:
        mw.progress.finish()
        done(results, cancelled)

    mw.progress.start(label="Comparing cards visually…", max=len(nids), parent=parent, immediate=True)
    comparer = VisualComparer(mw, nids, render, mw.serverURL(), progress, finished)
    comparer.start()


def apply_changes(config: dict, visual: dict | None) -> None:
    applied: list = []
    tagged: dict = {"tag": None, "count": 0}

    def op(col):
        if config["backup_before_apply"]:
            mw.create_backup_now()
        # Plan again, so edits made while the dialog was open are not overwritten.
        fresh, _ = plan_all(col, config)
        undo_entry = col.add_custom_undo_entry(ADDON_NAME)
        for plan in fresh:
            apply_plan(col, plan)
            applied.append(plan)
        if config["tag_changed_notes"]:
            if visual is not None:
                nids, tag = list(visual), TAG_CHANGED
            else:
                nids, tag = [n for p in fresh for n in p.check.affected], TAG_CHECK
            if nids:
                col.tags.bulk_add(nids, tag)
                tagged.update(tag=tag, count=len(nids))
        return col.merge_undo_entries(undo_entry)

    def on_done(_changes) -> None:
        save_css_copies(applied)
        saved = sum(p.saved_bytes for p in applied)
        message = (f"Done: note fields are {saved / 1e6:.1f} MB smaller.\n\n"
                   "Run Tools → Check Database to shrink the collection file, then sync.")
        if tagged["count"]:
            what = "look different" if tagged["tag"] == TAG_CHANGED else "could look different"
            message += (f"\n\n{tagged['count']:,} notes that {what} are tagged {tagged['tag']}. "
                        "Show them in the Browser now?")
            if askUser(message, parent=mw, title=ADDON_NAME):
                open_browser(f"tag:{tagged['tag']}")
        else:
            showInfo(message, parent=mw, title=ADDON_NAME)

    CollectionOp(parent=mw, op=op).success(on_done).run_in_background()


def on_menu() -> None:
    config = get_config()
    if not config["note_types"]:
        on_settings()
        return
    (QueryOp(parent=mw, op=lambda col: plan_all(col, config),
             success=lambda result: on_planned(result, config))
     .with_progress("Yomitan CSS Dedup: analysing notes…")
     .run_in_background())


def on_show_changed() -> None:
    if mw.col.find_notes("tag:yomitan-css-dedup::*"):
        open_browser("tag:yomitan-css-dedup::*")
    else:
        tooltip("No notes are tagged yomitan-css-dedup::… yet.", parent=mw)


def on_settings() -> bool:
    def show(stats) -> None:
        dialog = ConfigDialog(mw, stats, get_config(), ADDON_DIR / "user_files")
        if dialog.exec():
            mw.addonManager.writeConfig(__name__, dialog.result_config())

    (QueryOp(parent=mw, op=note_type_stats, success=show)
     .with_progress("Yomitan CSS Dedup: counting notes…")
     .run_in_background())
    return True  # handled: don't open Anki's JSON config editor


menu = QMenu(ADDON_NAME, mw)
for label, handler in (("Shrink notes…", on_menu), ("Show changed notes", on_show_changed),
                       ("Settings…", on_settings)):
    action = QAction(label, menu)
    action.triggered.connect(handler)
    menu.addAction(action)
mw.form.menuTools.addMenu(menu)
mw.addonManager.setConfigAction(__name__, on_settings)

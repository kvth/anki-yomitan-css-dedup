"""Yomitan CSS Dedup: Anki add-on entry point (Tools → Yomitan CSS Dedup…)."""

from __future__ import annotations

from pathlib import Path

from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import QAction
from aqt.utils import askUser, showInfo, showWarning

from .dedup import apply_plan, plan_notetype

ADDON_DIR = Path(__file__).parent
ADDON_NAME = "Yomitan CSS Dedup"


def get_config() -> dict:
    config = mw.addonManager.getConfig(__name__) or {}
    return {
        "note_types": list(config.get("note_types", ["Yomitan"])),
        "backup_before_apply": bool(config.get("backup_before_apply", True)),
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


def on_planned(result: tuple[list, list[str]], config: dict) -> None:
    plans, missing = result
    lines = [p.summary() for p in plans]
    if missing:
        lines.append(f"Note types not found: {', '.join(missing)} "
                     "(change them in Tools → Add-ons → Yomitan CSS Dedup → Config).")
    plans = [p for p in plans if p.has_changes]
    if not plans:
        showInfo("Nothing to do.\n\n" + "\n\n".join(lines), parent=mw, title=ADDON_NAME)
        return
    question = ("\n\n".join(lines)
                + "\n\nApply these changes? Card text and formatting stay the same. "
                  "You can undo with Edit → Undo.")
    if not askUser(question, parent=mw, title=ADDON_NAME):
        return

    applied: list = []

    def op(col):
        if config["backup_before_apply"]:
            mw.create_backup_now()
        # Plan again, so edits made while the dialog was open are not overwritten.
        fresh, _ = plan_all(col, config)
        undo_entry = col.add_custom_undo_entry(ADDON_NAME)
        for plan in fresh:
            apply_plan(col, plan)
            applied.append(plan)
        return col.merge_undo_entries(undo_entry)

    def on_done(_changes) -> None:
        save_css_copies(applied)
        saved = sum(p.saved_bytes for p in applied)
        showInfo(f"Done: note fields are {saved / 1e6:.1f} MB smaller.\n\n"
                 "Run Tools → Check Database to shrink the collection file, then sync.",
                 parent=mw, title=ADDON_NAME)

    CollectionOp(parent=mw, op=op).success(on_done).run_in_background()


def on_menu() -> None:
    config = get_config()
    if not config["note_types"]:
        showWarning("No note types configured.", parent=mw, title=ADDON_NAME)
        return
    (QueryOp(parent=mw, op=lambda col: plan_all(col, config),
             success=lambda result: on_planned(result, config))
     .with_progress("Yomitan CSS Dedup: analysing notes…")
     .run_in_background())


action = QAction(f"{ADDON_NAME}…", mw)
action.triggered.connect(on_menu)
mw.form.menuTools.addAction(action)

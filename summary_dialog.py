"""Window shown after the analysis: what would change, the render check, an optional
visual comparison, and the buttons to look at notes in the Browser or apply."""

from __future__ import annotations

from typing import Callable

from aqt.qt import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    Qt,
    QVBoxLayout,
)


class SummaryDialog(QDialog):
    def __init__(self, parent, text: str, candidates: int, identical: bool,
                 on_compare: Callable[[], None], on_show: Callable[[list], None],
                 on_apply: Callable[[], None]):
        super().__init__(parent)
        self.setWindowTitle("Yomitan CSS Dedup")
        self.setMinimumSize(640, 520)
        self.on_show = on_show

        details = QPlainTextEdit(text)
        details.setReadOnly(True)

        self.visual_label = QLabel()
        self.visual_label.setWordWrap(True)
        self.results = QListWidget()
        self.results.setVisible(False)
        self.results.itemDoubleClicked.connect(lambda item: on_show([item.data(Qt.ItemDataRole.UserRole)]))
        if identical:
            self.visual_label.setText("All cards keep exactly the same CSS rules, so no card can look different.")
        else:
            self.visual_label.setText(
                f"<b>{candidates:,} notes could look different.</b> Most of these changes have no visible "
                "effect. <i>Compare visually</i> renders each of them before and after and lists the "
                "notes that really look different (takes a few minutes).")

        buttons = QDialogButtonBox()
        self.compare_button = QPushButton("Compare visually…")
        self.compare_button.setEnabled(not identical)
        self.compare_button.clicked.connect(on_compare)
        self.show_button = QPushButton("Show in Browser")
        self.show_button.setEnabled(not identical)
        self.show_button.setToolTip("Open the notes listed below, or all notes that could look different")
        self.show_button.clicked.connect(self._show_all)
        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(on_apply)
        buttons.addButton(self.compare_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.show_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        (apply_button if identical else self.compare_button).setDefault(True)

        layout = QVBoxLayout(self)
        layout.addWidget(details, 1)
        layout.addWidget(self.visual_label)
        layout.addWidget(self.results, 1)
        layout.addWidget(buttons)

        self.candidate_nids: list = []
        self.visible_nids: list | None = None

    def _show_all(self) -> None:
        self.on_show(self.visible_nids if self.visible_nids is not None else self.candidate_nids)

    def set_results(self, rows: list, cancelled: bool) -> None:
        """rows: (nid, label, detail) for every note that looks different."""
        self.visible_nids = [nid for nid, _, _ in rows]
        self.compare_button.setEnabled(cancelled)
        self.results.clear()
        for nid, label, detail in rows:
            item = QListWidgetItem(f"{label}   –   {detail}")
            item.setData(Qt.ItemDataRole.UserRole, nid)
            self.results.addItem(item)
        self.results.setVisible(bool(rows))
        prefix = "Comparison cancelled; so far " if cancelled else ""
        if rows:
            self.visual_label.setText(
                f"<b>{prefix}{len(rows)} note{'s' if len(rows) != 1 else ''} look different.</b> "
                "Double-click one to open it in the Browser.")
        else:
            self.visual_label.setText(f"<b>{prefix}no note looks different.</b>")
        self.show_button.setEnabled(bool(rows))

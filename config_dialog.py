"""Settings window, shown for Tools → Yomitan CSS Dedup → Settings… and the add-on's Config button."""

from __future__ import annotations

from pathlib import Path

from aqt.qt import (
    QCheckBox,
    QDesktopServices,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    Qt,
    QTreeWidget,
    QTreeWidgetItem,
    QUrl,
    QVBoxLayout,
)


class ConfigDialog(QDialog):
    def __init__(self, parent, stats: list, config: dict, css_folder: Path):
        """stats: dedup.NoteTypeStats for every note type; config: the current settings."""
        super().__init__(parent)
        self.setWindowTitle("Yomitan CSS Dedup – Settings")
        self.setMinimumWidth(560)
        self.stats = stats
        self.css_folder = css_folder

        intro = QLabel(
            "<b>Note types to shrink</b><br>"
            "Yomitan copies each dictionary's stylesheet into every note. Pick the note types "
            "whose notes should have them moved into the note type's styling.")
        intro.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Note type", "Notes with Yomitan stylesheets"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        selected = set(config["note_types"])
        for s in stats:
            if not s.notes and s.name not in selected:  # empty note types only clutter the list
                continue
            self._add_item(s.name, f"{s.with_styles:,} of {s.notes:,}" if s.notes else "no notes",
                           s.name in selected, dim=not s.with_styles)
        for name in sorted(selected - {s.name for s in stats}):
            self._add_item(name, "not found in this collection", True, dim=True)

        detect = QPushButton("Select detected")
        detect.setToolTip("Select exactly the note types whose notes contain Yomitan stylesheets")
        detect.clicked.connect(self.select_detected)
        detected = sum(1 for s in stats if s.with_styles)
        hint = QLabel(f"{detected} note type{'s' if detected != 1 else ''} with Yomitan stylesheets found."
                      if detected else "No notes with Yomitan stylesheets found.")
        hint.setStyleSheet("color: gray")
        row = QHBoxLayout()
        row.addWidget(hint, 1)
        row.addWidget(detect)

        self.backup = QCheckBox("Create an Anki backup before applying changes (recommended)")
        self.backup.setChecked(config["backup_before_apply"])
        self.tag = QCheckBox("Tag notes that look different (yomitan-css-dedup::…) to find them in the Browser")
        self.tag.setChecked(config.get("tag_changed_notes", True))
        self.tag.setToolTip("After a visual comparison: the notes that look different (::changed). "
                            "Without one: all notes the render check lists (::check).")

        css_label = QLabel("After each run, a copy of the CSS moved into the note type is saved, "
                           "in case the note type's styling is ever replaced.")
        css_label.setWordWrap(True)
        css_label.setStyleSheet("color: gray")
        open_css = QPushButton("Open folder")
        open_css.clicked.connect(self.open_css_folder)
        css_row = QHBoxLayout()
        css_row.addWidget(css_label, 1)
        css_row.addWidget(open_css)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.tree, 1)
        layout.addLayout(row)
        layout.addSpacing(8)
        layout.addWidget(QLabel("<b>Safety</b>"))
        layout.addWidget(self.backup)
        layout.addWidget(self.tag)
        layout.addLayout(css_row)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    def _add_item(self, name: str, count_text: str, checked: bool, dim: bool) -> None:
        item = QTreeWidgetItem([name, count_text])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if dim:
            item.setForeground(0, Qt.GlobalColor.gray)
            item.setForeground(1, Qt.GlobalColor.gray)
        self.tree.addTopLevelItem(item)

    def _items(self):
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def select_detected(self) -> None:
        detected = {s.name for s in self.stats if s.with_styles}
        for item in self._items():
            item.setCheckState(0, Qt.CheckState.Checked if item.text(0) in detected else Qt.CheckState.Unchecked)

    def open_css_folder(self) -> None:
        self.css_folder.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.css_folder)))

    def result_config(self) -> dict:
        return {
            "note_types": [i.text(0) for i in self._items() if i.checkState(0) == Qt.CheckState.Checked],
            "backup_before_apply": self.backup.isChecked(),
            "tag_changed_notes": self.tag.isChecked(),
        }

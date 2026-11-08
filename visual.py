"""Visual comparison: render cards before and after in hidden web views and compare
what the browser engine computes for every element.

The render check lists the notes whose CSS rules change; many of those changes
have no visible effect. This renders each listed note twice and compares, per
element, the computed styles (colours, fonts, sizes, borders, margins, …).
Elements that only moved, without a style change of their own, don't count:
they follow a change elsewhere or the page was still settling.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Callable

from aqt.qt import QObject, Qt, QTimer, QUrl, QWebEngineSettings, QWebEngineView

PROPS = ["display", "visibility", "opacity", "color", "background-color", "background-image",
         "font-family", "font-size", "font-weight", "font-style", "line-height", "text-align",
         "vertical-align", "text-decoration-line", "text-decoration-color", "text-transform",
         "white-space", "writing-mode", "list-style-type", "border-top-style", "border-top-width",
         "border-top-color", "border-right-style", "border-right-width", "border-bottom-style",
         "border-bottom-width", "border-bottom-color", "border-left-style", "border-left-width",
         "border-radius", "box-shadow", "text-shadow", "transform", "filter", "margin-top",
         "margin-right", "margin-bottom", "margin-left", "padding-top", "padding-right",
         "padding-bottom", "padding-left"]

# One row per element: [description, box, *PROPS, ::before, ::after]
SNAPSHOT_JS = """
(() => {
  const props = %s;
  const skip = new Set(["STYLE", "SCRIPT", "LINK", "META", "BR"]);
  const rows = [];
  for (const e of document.body.querySelectorAll("*")) {
    if (skip.has(e.tagName)) continue;
    const cs = getComputedStyle(e), r = e.getBoundingClientRect();
    const cls = typeof e.className === "string" && e.className.trim() ? "." + e.className.trim().split(/\\s+/).join(".") : "";
    const sc = e.dataset && e.dataset.scContent ? "[data-sc-content=" + e.dataset.scContent + "]" : "";
    const row = [e.tagName.toLowerCase() + cls + sc, [r.x, r.y, r.width, r.height].map(Math.round).join(",")];
    for (const p of props) {
      let v = cs.getPropertyValue(p);
      if (p === "vertical-align" && v === "0px") v = "baseline";  // renders the same
      row.push(v);
    }
    for (const pseudo of ["::before", "::after"]) {
      const ps = getComputedStyle(e, pseudo);
      row.push(ps.content === "none" ? "none" : [ps.content, ps.display, ps.color, ps.fontSize].join(" "));
    }
    rows.push(row);
  }
  return JSON.stringify(rows);
})()
""" % json.dumps(PROPS)

COLUMNS = ["box"] + PROPS + ["::before", "::after"]


def compare_snapshots(before: list, after: list) -> tuple[int, list[str]]:
    """Number of elements whose own styles changed, and up to 5 descriptions."""
    samples = []
    count = 0
    if len(before) != len(after):
        samples.append(f"different number of elements: {len(before)} → {len(after)}")
    for a, b in zip(before, after):
        changed = [i for i in range(2, len(a)) if a[i] != b[i]]
        if not changed:
            continue
        count += 1
        if len(samples) < 5:
            samples.append(f"{a[0]}: " + "; ".join(f"{COLUMNS[i - 1]} {a[i]} → {b[i]}" for i in changed))
    if len(before) != len(after):
        count = max(count, 1)
    return count, samples


def page_html(card_html: str, card_ord: int, base_url: str) -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            f"<base href='{base_url}'></head>"
            f"<body class='card card{card_ord + 1}'><div id='qa'>{card_html}</div></body></html>")


class VisualComparer(QObject):
    """Compares notes one by one; the results arrive via on_done.

    render(nid) returns (before_html, after_html, card_ord) or None to skip.
    on_progress(done, total) returns False to cancel.
    on_done(results) gets {nid: (changed_elements, samples)} for notes that look different.
    """

    SETTLE_MS = 200
    RECHECK_MS = 1000

    def __init__(self, parent, nids: list, render: Callable, base_url: str,
                 on_progress: Callable[[int, int], bool], on_done: Callable[[dict], None]):
        super().__init__(parent)
        self.nids, self.render, self.base_url = list(nids), render, base_url
        self.on_progress, self.on_done = on_progress, on_done
        self.index, self.results, self.generation = 0, {}, 0
        self.tmp = Path(tempfile.mkdtemp(prefix="yomitan-css-dedup-"))
        self.views = []
        for _ in range(2):
            view = QWebEngineView()
            view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            view.resize(600, 900)
            # the page is a temporary file; let it load images and fonts from Anki's media server
            view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            view.show()
            view.loadFinished.connect(self._loaded)
            self.views.append(view)

    def start(self) -> None:
        self._next()

    def _next(self) -> None:
        while self.index < len(self.nids):
            if not self.on_progress(self.index, len(self.nids)):
                break
            nid = self.nids[self.index]
            self.index += 1
            try:
                rendered = self.render(nid)
            except Exception:  # a card that can't be rendered is skipped, not fatal
                rendered = None
            if rendered is None:
                continue
            self.current, self.attempt = nid, 0
            before, after, card_ord = rendered
            for i, body in enumerate((before, after)):
                self._path(i).write_text(page_html(body, card_ord, self.base_url), encoding="utf-8")
            self._load()
            return
        self._finish()

    def _path(self, i: int) -> Path:
        return self.tmp / f"{'before' if i == 0 else 'after'}.html"

    def _load(self) -> None:
        self.pending, self.snapshots = 2, [None, None]
        self.generation += 1
        for i, view in enumerate(self.views):
            view.load(QUrl.fromLocalFile(str(self._path(i))))

    def _loaded(self, _ok: bool) -> None:
        self.pending -= 1
        if self.pending == 0:
            generation = self.generation
            QTimer.singleShot(self.SETTLE_MS, lambda: self._snapshot(generation))

    def _snapshot(self, generation: int) -> None:
        if generation != self.generation:
            return
        self.snapshots = [None, None]
        for i, view in enumerate(self.views):
            view.page().runJavaScript(SNAPSHOT_JS, lambda result, i=i: self._got(generation, i, result))

    def _got(self, generation: int, i: int, result) -> None:
        if generation != self.generation:
            return
        self.snapshots[i] = json.loads(result) if result else []
        if any(s is None for s in self.snapshots):
            return
        count, samples = compare_snapshots(*self.snapshots)
        # Card templates may still be running scripts, so a difference only counts if it
        # survives a second look a moment later and then a fresh load of both pages.
        if count and self.attempt == 0:
            self.attempt = 1
            QTimer.singleShot(self.RECHECK_MS, lambda: self._snapshot(generation))
            return
        if count and self.attempt == 1:
            self.attempt = 2
            self._load()
            return
        if count:
            self.results[self.current] = (count, samples)
        self._next()

    def _finish(self) -> None:
        for view in self.views:
            view.close()
            view.deleteLater()
        for f in self.tmp.glob("*"):
            f.unlink()
        self.tmp.rmdir()
        self.on_done(self.results)

# Yomitan CSS Dedup

An Anki add-on that shrinks notes created by [Yomitan](https://github.com/yomidevs/yomitan)
without changing what the cards show.

Yomitan copies each dictionary's full stylesheet into every note it creates
(9–60 KB per dictionary, per note). With a few thousand cards this pushes
the collection over AnkiWeb's 300 MB limit
("Your collection file is too large to send to AnkiWeb").
On one real collection of 7,683 Yomitan notes, 180 MB of the 288 MB of note
text was copies of just 10 stylesheets.

Yomitan CSS Dedup stores that CSS once in the note type instead:

| | Before | After |
|---|---|---|
| Note fields | 287.6 MB | 113.2 MB |
| `collection.anki2` | 314.5 MB | 138.2 MB |

## What it does

It moves the dictionary stylesheets out of the note fields into the note type's
Styling:

- Rules limited to one dictionary (every selector contains
  `[data-dictionary="…"]`) are moved and stored once per dictionary. When notes
  contain different versions of a dictionary's stylesheet, the version used by
  the most notes is kept. These rules can only match that dictionary's entries,
  so it doesn't matter that every card now loads them.
- All other rules stay in the note as a small `<style>` block (each rule once),
  for example Yomitan's compact glossary rules, which match every glossary list
  on a card. That way they keep reaching exactly the notes they reached before.
  `<style>` blocks without any rule limited to a dictionary aren't touched.
- The moved stylesheets are appended at the end of the Styling, which is the same
  position in the cascade they had inside the card.

Glossary text, inline styles, `data-*` attributes and everything else stay as they are.
Running it again only processes what is new.

## Render check

Before anything is written, a render check compares for every note the CSS rules
that could apply to it before and after. Since only `<style>` blocks are removed,
this finds every card that could look different:

- a note had another version of a dictionary's stylesheet than the one kept,
- a note has entries of a dictionary but never had its stylesheet,
- rules that aren't limited to one dictionary (e.g. Yomitan's compact glossary
  rules) would reach notes that didn't have them.

A rule only counts for a note if it can match it: rules for a dictionary only
for notes with entries from it, rules needing a class only if the class appears
in the note or the card template. Rules browsers ignore anyway (broken by a stray
`<br>`) are skipped.

The render check lists every card whose CSS rules change, but most of those changes
have no visible effect. The add-on's **Compare visually…** button goes one step further:
it renders each listed note before and after in a hidden window (with Anki's own browser
engine, images and fonts) and compares the computed styles of every element: colours,
fonts, sizes, borders, margins and so on. A difference only counts if it is still there
after a second look and after reloading both versions, so card scripts that are still
running don't cause false alarms. On a collection of 7,709 notes, 1,266 were listed by
the render check and 12 really looked different.

`cli.py --apply` refuses when the render check lists notes, unless you add `--ignore-check`.

## Install as an Anki add-on

**From a release (easiest)**

1. Download `yomitan-css-dedup.ankiaddon` from the
   [latest release](https://github.com/kvth/anki-yomitan-css-dedup/releases/latest).
2. In Anki: **Tools → Add-ons → Install from file…** and pick the downloaded file.
3. Restart Anki.

**Build it yourself**

```bash
git clone https://github.com/kvth/anki-yomitan-css-dedup.git
cd anki-yomitan-css-dedup
./build-addon.sh
```

This runs the tests and writes `dist/yomitan-css-dedup.ankiaddon`. Install that
file the same way (**Tools → Add-ons → Install from file…**).

## Use the add-on

1. **Tools → Yomitan CSS Dedup → Shrink notes…** analyses your notes and shows how much
   it would save and which notes could look different (see [Render check](#render-check)).
2. Optional: **Compare visually…** renders each of those notes before and after and lists
   the ones that really look different (a few minutes for ~1,000 notes). Double-click one,
   or use **Show in Browser**, to look at it. The window stays open meanwhile.
3. **Apply**. Anki makes a backup first, and **Edit → Undo** reverts everything. The notes
   that look different are tagged `yomitan-css-dedup::changed` (without a visual comparison:
   all listed notes, `yomitan-css-dedup::check`), so you can check them later with
   **Tools → Yomitan CSS Dedup → Show changed notes**. Remove the tag when you're done.
4. Run **Tools → Check Database** to shrink the collection file, then sync.

Yomitan keeps adding stylesheets to new cards, so run it again from time to time.

**Settings** (**Tools → Yomitan CSS Dedup → Settings…**, or the Config button in the
add-on manager): pick the note types to process. The list shows how many notes of each
note type contain Yomitan stylesheets, and **Select detected** picks exactly those. You
can also turn off the backup before applying and open the folder with the saved CSS copies.
The default note type is `Yomitan`.

## Run standalone (without installing the add-on)

`cli.py` does the same from the command line. It needs Anki's `anki` Python
package in the same version as your Anki, so the easiest way is to run it with
the Python that comes with Anki. **Close Anki first.**

```bash
git clone https://github.com/kvth/anki-yomitan-css-dedup.git
cd anki-yomitan-css-dedup

# dry run: only shows what would change
~/.local/share/AnkiProgramFiles/.venv/bin/python cli.py

# apply: copies collection.anki2 to a backup next to it, writes, then compacts the file
~/.local/share/AnkiProgramFiles/.venv/bin/python cli.py --apply
```

Anki's Python and the collection are in different places per system:

| System | Anki's Python | Collection (pass with `--collection`) |
|---|---|---|
| Linux | `~/.local/share/AnkiProgramFiles/.venv/bin/python` | `~/.local/share/Anki2/User 1/collection.anki2` (default) |
| macOS | `~/Library/Application Support/AnkiProgramFiles/.venv/bin/python` | `~/Library/Application Support/Anki2/User 1/collection.anki2` |
| Windows | `%LOCALAPPDATA%\AnkiProgramFiles\.venv\Scripts\python.exe` | `%APPDATA%\Anki2\User 1\collection.anki2` |

Older Anki installs without the launcher don't have that Python; use a virtual
environment with `pip install anki==<your Anki version>` instead.

Options: `--collection PATH`, `--notetype NAME` (repeatable, default `Yomitan`),
`--no-backup`, `--no-vacuum`, `--ignore-check`. Afterwards open Anki and sync.

## Good to know

- The CSS now lives in the note type's Styling, between
  `/* BEGIN yomitan-dictionary-styles … */` and `/* END yomitan-dictionary-styles */`.
  Don't edit inside these markers. If you replace the Styling (for example with a
  new version of a card template), copy that section back. A copy is saved after
  every run: in the add-on's `user_files/` folder, or next to the collection when
  using `cli.py`.
- Yomitan turns line breaks inside some stylesheets into `<br>`, which breaks a few
  rules. Those versions are rare, so the most-used (clean) version is normally the
  one that is kept, and cards that had a broken version get the complete rules.
- If notes have different versions of a dictionary's stylesheet, cards with the
  less common version get the most common one. The render check lists how many
  notes that affects per dictionary; check a few of them after applying.

## Development

```bash
python3 -m unittest discover tests   # tests only
./build-addon.sh                     # tests + dist/yomitan-css-dedup.ankiaddon
```

Pushing a `v*` tag builds the add-on on GitHub Actions and attaches it to a release.

`dedup.py` holds the logic and only uses the `anki` collection API.
`__init__.py` is the add-on wrapper, with `summary_dialog.py`, `config_dialog.py` and
`visual.py` (the visual comparison); `cli.py` is the command line wrapper.

## License

MIT, see [LICENSE](LICENSE).

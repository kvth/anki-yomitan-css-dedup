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
| Note fields | 287.6 MB | 107.4 MB |
| `collection.anki2` | 314.5 MB | 132.5 MB |

## What it does

It moves the `<style>` blocks out of the note fields into the note type's
Styling:

- Stylesheets of a dictionary (they contain `data-dictionary="…"`) are stored
  once per dictionary. When notes contain different versions of a dictionary's
  stylesheet, the version used by the most notes is kept.
- Other `<style>` blocks are only merged with exact copies of themselves, never
  with each other.
- Stylesheets are kept whole and appended at the end of the Styling, which is
  the same position in the cascade they had inside the card.

Glossary text, inline styles, `data-*` attributes and everything else stay as they are.
Running it again only processes what is new.

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

1. **Tools → Yomitan CSS Dedup…** analyses your notes and shows how much it would save.
2. Confirm to apply. Anki makes a backup first, and **Edit → Undo** reverts it.
3. Run **Tools → Check Database** to shrink the collection file, then sync.

Yomitan keeps adding stylesheets to new cards, so run it again from time to time.

Settings (**Tools → Add-ons → Yomitan CSS Dedup → Config**): see [config.md](config.md).
The default note type is `Yomitan`; add the names of your note types if they differ.

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
`--no-backup`, `--no-vacuum`. Afterwards open Anki and sync.

## Good to know

- The CSS now lives in the note type's Styling, between
  `/* BEGIN yomitan-dictionary-styles … */` and `/* END yomitan-dictionary-styles */`.
  Don't edit inside these markers. If you replace the Styling (for example with a
  new version of a card template), copy that section back. A copy is saved after
  every run: in the add-on's `user_files/` folder, or next to the collection when
  using `cli.py`.
- Yomitan turns line breaks inside some stylesheets into `<br>`, which breaks a few
  rules. Those versions are rare, so the most-used (clean) version is normally the
  one that is kept.

## Development

```bash
python3 -m unittest discover tests   # tests only
./build-addon.sh                     # tests + dist/yomitan-css-dedup.ankiaddon
```

Pushing a `v*` tag builds the add-on on GitHub Actions and attaches it to a release.

`dedup.py` holds the logic and only uses the `anki` collection API.
`__init__.py` is the add-on wrapper, `cli.py` the command line wrapper.

## License

MIT, see [LICENSE](LICENSE).

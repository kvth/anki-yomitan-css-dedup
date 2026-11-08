#!/usr/bin/env bash
# Build dist/yomitan-css-dedup.ankiaddon, the file you install in Anki with
# Tools → Add-ons → Install from file…
set -euo pipefail
cd "$(dirname "$0")"

FILES=(__init__.py dedup.py config_dialog.py summary_dialog.py visual.py manifest.json config.json config.md user_files/README.txt LICENSE README.md)
OUT=dist/yomitan-css-dedup.ankiaddon

python3 -m py_compile __init__.py dedup.py config_dialog.py summary_dialog.py visual.py cli.py
python3 -m unittest discover -s tests -q

mkdir -p dist
rm -f "$OUT"
# An .ankiaddon is a plain zip with the add-on files at the top level.
python3 - "$OUT" "${FILES[@]}" <<'PY'
import sys, zipfile
out, *files = sys.argv[1:]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(f)
PY
echo "Wrote $OUT"

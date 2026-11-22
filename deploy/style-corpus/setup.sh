#!/usr/bin/env bash
# One-time setup on the server (run as pancds). Creates ~/style_corpus with its own venv.
set -euo pipefail
HOME_DIR="${STYLE_CORPUS_HOME:-$HOME/style_corpus}"
SRC="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME_DIR/out"
chmod 700 "$HOME_DIR"
if [ ! -x "$HOME_DIR/venv/bin/python" ]; then
  python3 -m venv "$HOME_DIR/venv"
fi
"$HOME_DIR/venv/bin/pip" install -q --upgrade pip
"$HOME_DIR/venv/bin/pip" install -q "pymupdf>=1.24" "numpy>=1.26"
"$HOME_DIR/venv/bin/pip" install -q "fastembed>=0.4" || echo "fastembed unavailable for this Python; exemplar search will use keywords (FTS5)."
if [ ! -f "$HOME_DIR/zotero.env" ]; then
  umask 077
  printf 'ZOTERO_API_KEY=\nZOTERO_LIBRARY_ID=\nZOTERO_LIBRARY_TYPE=user\n' > "$HOME_DIR/zotero.env"
  echo "Fill in $HOME_DIR/zotero.env (a READ-ONLY Zotero key is enough)."
fi
echo "Code: $SRC  Data: $HOME_DIR"

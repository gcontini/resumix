#!/bin/sh
# Build the resumix client executable and install it into resumix-data/gab.
#
# The spec and the build command are the ones CI uses (.github/workflows/ci.yml,
# job "client"). PyInstaller does not cross-compile, so this produces a binary
# for the machine it runs on.
#
# No `uv sync` first: `uv run` syncs what it needs, and a plain `uv sync` would
# remove the docs group from the venv.
#
# Only the binary is replaced. resumix-data/gab also holds the user's own data
# and a resumix.toml with a bearer token in it; nothing else there is touched.
set -eu

cd "$(dirname "$0")/.."

DEST="resumix-data/gab"

uv run --with pyinstaller pyinstaller --noconfirm client/packaging/resumix.spec

./dist/resumix --help >/dev/null
./dist/resumix version

cp dist/resumix "$DEST/resumix"
chmod +x "$DEST/resumix"

# From inside the folder, so its resumix.toml is the one picked up.
(cd "$DEST" && ./resumix version)

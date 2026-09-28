---
name: build-client
description: Build the resumix client executable with PyInstaller and install it into resumix-data/gab. Use when asked to build, rebuild, refresh or deploy the client binary.
---

# Build the client and install it into resumix-data/gab

Run from the repository root. The spec and the build command are the same
ones CI uses (`.github/workflows/ci.yml`, job `client`).

1. Build:

   ```bash
   uv run --with pyinstaller pyinstaller --noconfirm client/packaging/resumix.spec
   ```

   No `uv sync` first: `uv run` syncs what it needs, and a plain `uv sync`
   would remove the docs group from the venv. The output is `dist/resumix`. PyInstaller does not cross-compile, so this
   produces a Linux binary here.

2. Check it starts:

   ```bash
   ./dist/resumix --help >/dev/null
   ./dist/resumix version
   ```

3. Copy it, replacing the previous binary:

   ```bash
   cp dist/resumix resumix-data/gab/resumix
   chmod +x resumix-data/gab/resumix
   ```

4. Check the installed copy from inside the folder, so its `resumix.toml` is
   the one picked up:

   ```bash
   (cd resumix-data/gab && ./resumix version)
   ```

Report the version it printed. Touch nothing else in `resumix-data/gab`: it
holds the user's own data and `resumix.toml`, with a bearer token in it.
`resumix-data/` is gitignored, and nothing here is committed.

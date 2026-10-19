#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_ROOT="$ROOT/build/macos"
APP="$BUILD_ROOT/CSBoard.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
RUNTIME="$RESOURCES/runtime"
APP_ROOT="$RESOURCES/app"
DMG="$ROOT/dist/CSBoard-0.1.0-$(uname -m).dmg"

die() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

command -v clang >/dev/null 2>&1 || die "clang is required"
command -v hdiutil >/dev/null 2>&1 || die "hdiutil is required"
command -v rsync >/dev/null 2>&1 || die "rsync is required"
command -v npm >/dev/null 2>&1 || die "npm is required"

PYTHON="$ROOT/.venv/bin/python"
NODE="$(command -v node || true)"
[ -x "$PYTHON" ] || die "Missing $PYTHON; create the project environment first"
[ -x "$NODE" ] || die "Node.js is required"
"$PYTHON" -c 'import PyInstaller' >/dev/null 2>&1 || die "Install PyInstaller in .venv before packaging"

rm -rf "$BUILD_ROOT"
mkdir -p "$APP/Contents/MacOS" "$RESOURCES" "$RUNTIME" "$APP_ROOT" "$ROOT/dist"
export CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-$BUILD_ROOT/clang-cache}"
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$BUILD_ROOT/pyinstaller-config}"

printf '%s\n' 'Building frontend…'
(cd "$ROOT/web" && NEXT_PUBLIC_API_BASE=http://127.0.0.1:18765 npm run build)

printf '%s\n' 'Building backend…'
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name CSBoardBackend \
  --distpath "$BUILD_ROOT/backend-dist" \
  --workpath "$BUILD_ROOT/pyinstaller-work" \
  --specpath "$BUILD_ROOT" \
  --paths "$ROOT" \
  --hidden-import webapp.server \
  --hidden-import scripts.semantic_timeline \
  --collect-all gradio_client \
  --collect-all uvicorn \
  "$ROOT/packaging/macos/backend_entry.py"

printf '%s\n' 'Compiling macOS launcher…'
clang \
  -O \
  -framework Cocoa \
  -framework Foundation \
  -framework WebKit \
  "$ROOT/packaging/macos/CSBoardLauncher.m" \
  -o "$CONTENTS/MacOS/CSBoardLauncher"

cp "$ROOT/packaging/macos/Info.plist" "$CONTENTS/Info.plist"
cp -R "$BUILD_ROOT/backend-dist/CSBoardBackend" "$RUNTIME/backend"
cp "$NODE" "$RUNTIME/node"
chmod +x "$RUNTIME/node"

rsync -a "$ROOT/assets/" "$APP_ROOT/assets/"
rsync -a "$ROOT/scripts/" "$APP_ROOT/scripts/"
rsync -a "$ROOT/video_renderer/" "$APP_ROOT/video_renderer/" \
  --exclude '.cache' \
  --exclude 'dist'
rsync -a "$ROOT/web/dist/" "$APP_ROOT/web/dist/"
rsync -a "$ROOT/web/public/" "$APP_ROOT/web/public/"
rsync -a "$ROOT/web/node_modules/" "$APP_ROOT/web/node_modules/" \
  --exclude '.cache'
cp "$ROOT/web/package.json" "$APP_ROOT/web/package.json"
cp "$ROOT/web/package-lock.json" "$APP_ROOT/web/package-lock.json"
cp "$ROOT/pronunciation.yaml" "$APP_ROOT/pronunciation.yaml"

mkdir -p "$APP_ROOT/webapp"
cp "$ROOT/webapp/server.py" "$APP_ROOT/webapp/server.py"

printf '%s\n' 'Creating DMG…'
rm -f "$DMG"
hdiutil create \
  -volname "白板声画工坊" \
  -srcfolder "$APP" \
  -ov \
  -format UDZO \
  "$DMG" >/dev/null

printf 'Created: %s\n' "$DMG"
du -sh "$APP" "$DMG"

#!/usr/bin/env bash
# Prueft, ob die Board-API v1 gegenueber dem letzten Release-Stand bricht (T3, CI).
#
# Vergleichsstand: packages/board/openapi/board-v1.json im letzten Tag v*; gibt es die
# Datei dort noch nicht (erstes Release mit v1), der Stand auf origin/main. Fehlt sie
# ueberall, fuehrt dieser Stand v1 ein und es gibt nichts zu vergleichen.
#
# oasdiff wird als Release-Archiv geladen und gegen die veroeffentlichte Pruefsumme
# geprueft (Version und SHA-256 hier fest, wie die Actions per Commit gepinnt sind).
set -euo pipefail

OASDIFF_VERSION="1.35.0"
OASDIFF_SHA256="a8023002fcb2eaa7f5758148a9303cb63d33b939886df312268bc0fc7b939140"   # linux_amd64.tar.gz
SPEC="packages/board/openapi/board-v1.json"
WORK="${RUNNER_TEMP:-$(mktemp -d)}/board-api"
mkdir -p "$WORK"

base=""
tag="$(git describe --tags --abbrev=0 --match 'v*' 2>/dev/null || true)"
if [ -n "$tag" ] && git cat-file -e "$tag:$SPEC" 2>/dev/null; then
  base="$tag"
elif git cat-file -e "origin/main:$SPEC" 2>/dev/null; then
  base="origin/main"
fi
if [ -z "$base" ]; then
  echo "::notice::$SPEC gibt es weder im letzten Release ($tag) noch auf main: dieser Stand fuehrt v1 ein."
  exit 0
fi
git show "$base:$SPEC" > "$WORK/base.json"
echo "Vergleich gegen $base"

archive="oasdiff_${OASDIFF_VERSION}_linux_amd64.tar.gz"
curl -fsSL -o "$WORK/$archive" \
  "https://github.com/oasdiff/oasdiff/releases/download/v${OASDIFF_VERSION}/${archive}"
echo "${OASDIFF_SHA256}  $WORK/$archive" | sha256sum --check --strict
tar -xzf "$WORK/$archive" -C "$WORK" oasdiff

"$WORK/oasdiff" breaking "$WORK/base.json" "$SPEC" --fail-on ERR

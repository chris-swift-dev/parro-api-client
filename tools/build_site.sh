#!/usr/bin/env bash
# Assemble the GitHub Pages site: the landing page at the root, and stock Swagger UI with the PUBLIC
# spec (no sample payloads) in api/ (Plan 16 §5).
# Needs `npm ci --ignore-scripts` first (for node_modules/swagger-ui-dist).
# Usage: tools/build_site.sh [_site] [--no-release]   (--no-release: download buttons to the
# releases page, without asking GitHub for the latest release)
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:-_site}"
shift || true
dist="node_modules/swagger-ui-dist"
spec="openapi/parro.public.openapi.json"

[ -d "$dist" ] || { echo "error: $dist missing - run 'npm ci --ignore-scripts' first" >&2; exit 1; }
[ -f "$spec" ] || { echo "error: $spec missing - run 'npm run spec'" >&2; exit 1; }

rm -rf "$out"
mkdir -p "$out/api"
for f in index.html index.css swagger-ui.css swagger-ui-bundle.js swagger-ui-standalone-preset.js \
         favicon-16x16.png favicon-32x32.png; do
  cp "$dist/$f" "$out/api/"
done
cp site/swagger-initializer.js "$out/api/"
cp "$spec" "$out/api/parro.openapi.json"
cp "$spec" "$out/parro.openapi.json"  # its address before 0.12.0, which tools may use
sed -i.bak 's|<title>Swagger UI</title>|<title>Parro REST API (unofficial)</title>|' "$out/api/index.html" && rm -f "$out/api/index.html.bak"
echo "Swagger UI in $out/api/ (swagger-ui-dist $(node -p "require('./$dist/package.json').version"))"

python3 tools/build_landing.py "$out" "$@"

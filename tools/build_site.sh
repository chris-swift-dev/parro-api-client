#!/usr/bin/env bash
# Assemble the GitHub Pages site: stock Swagger UI + the PUBLIC spec (no sample payloads).
# Needs `npm ci --ignore-scripts` first (for node_modules/swagger-ui-dist).  Usage: tools/build_site.sh [_site]
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:-_site}"
dist="node_modules/swagger-ui-dist"
spec="openapi/parro.public.openapi.json"

[ -d "$dist" ] || { echo "error: $dist missing - run 'npm ci --ignore-scripts' first" >&2; exit 1; }
[ -f "$spec" ] || { echo "error: $spec missing - run 'npm run spec'" >&2; exit 1; }

rm -rf "$out"
mkdir -p "$out"
for f in index.html index.css swagger-ui.css swagger-ui-bundle.js swagger-ui-standalone-preset.js \
         favicon-16x16.png favicon-32x32.png; do
  cp "$dist/$f" "$out/"
done
cp site/swagger-initializer.js "$out/"
cp "$spec" "$out/parro.openapi.json"
sed -i.bak 's|<title>Swagger UI</title>|<title>Parro REST API (unofficial)</title>|' "$out/index.html" && rm -f "$out/index.html.bak"
echo "site assembled in $out/ (swagger-ui-dist $(node -p "require('./$dist/package.json').version"))"

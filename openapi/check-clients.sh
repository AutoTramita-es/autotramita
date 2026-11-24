#!/usr/bin/env bash
# Verify that TypeScript and Dart clients can be generated from openapi/openapi.json.
# Generated code is written to a temporary directory and discarded; it is not committed (F1).
set -euo pipefail

TS_GENERATOR_VERSION="7.13.0"   # must equal openapi/toolchain/package.json
TS_COMPILER_VERSION="5.6.3"     # must equal openapi/toolchain/package.json
DART_GENERATOR_IMAGE="openapitools/openapi-generator-cli:v7.10.0@sha256:f2054a5a7908ad81017d0f0839514ba5eab06ae628914ff71554d46fac1bcf7a"

root="$(cd "$(dirname "$0")/.." && pwd)"
spec="$root/openapi/openapi.json"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "TypeScript: openapi-typescript $TS_GENERATOR_VERSION, tsc $TS_COMPILER_VERSION (npm ci from the lockfile)"
mkdir -p "$work/tool"
cp "$root/openapi/toolchain/package.json" "$root/openapi/toolchain/package-lock.json" "$work/tool/"
(cd "$work/tool" && npm ci --ignore-scripts --no-audit --no-fund >/dev/null)
tool="$work/tool/node_modules/.bin"
test "$("$tool/tsc" --version)" = "Version $TS_COMPILER_VERSION"
test "$(node -p "require('$work/tool/node_modules/openapi-typescript/package.json').version")" = "$TS_GENERATOR_VERSION"
"$tool/openapi-typescript" "$spec" -o "$work/schema.d.ts" >/dev/null
test -s "$work/schema.d.ts"
"$tool/tsc" --noEmit --strict --skipLibCheck "$work/schema.d.ts"
grep -q "Problem" "$work/schema.d.ts"

echo "Dart: generating with $DART_GENERATOR_IMAGE"
mkdir -p "$work/dart"
docker run --rm --user "$(id -u):$(id -g)" -v "$spec:/spec/openapi.json:ro" -v "$work/dart:/out" "$DART_GENERATOR_IMAGE" \
  generate -g dart -i /spec/openapi.json -o /out >/dev/null
test -s "$work/dart/pubspec.yaml"
grep -rq "class Problem" "$work/dart/lib"

echo "Client generation check passed."

#!/usr/bin/env bash
# Verify that TypeScript and Dart clients can be generated from openapi/openapi.json.
# Generated code is written to a temporary directory and discarded; it is not committed (F1).
set -euo pipefail

TS_GENERATOR="openapi-typescript@7.13.0"
TS_COMPILER="typescript@5.6.3"
DART_GENERATOR_IMAGE="openapitools/openapi-generator-cli:v7.10.0"

root="$(cd "$(dirname "$0")/.." && pwd)"
spec="$root/openapi/openapi.json"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "TypeScript: generating with $TS_GENERATOR"
npx --yes "$TS_GENERATOR" "$spec" -o "$work/schema.d.ts" >/dev/null
test -s "$work/schema.d.ts"
npx --yes -p "$TS_COMPILER" tsc --noEmit --strict --skipLibCheck "$work/schema.d.ts"
grep -q "Problem" "$work/schema.d.ts"

echo "Dart: generating with $DART_GENERATOR_IMAGE"
mkdir -p "$work/dart"
docker run --rm --user "$(id -u):$(id -g)" -v "$spec:/spec/openapi.json:ro" -v "$work/dart:/out" "$DART_GENERATOR_IMAGE" \
  generate -g dart -i /spec/openapi.json -o /out --skip-validate-spec >/dev/null
test -s "$work/dart/pubspec.yaml"
grep -rq "class Problem" "$work/dart/lib"

echo "Client generation check passed."

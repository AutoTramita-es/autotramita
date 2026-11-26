#!/bin/sh
# Builds the provider jar from source against the jars of the pinned Keycloak image (no other
# dependency) and makes it reproducible: sorted inputs, fixed entry times, fixed manifest.
# Usage (inside the build stage): build.sh <keycloak-lib-dir> <output-jar>
set -eu
lib="$1"
out="$2"
here="$(cd "$(dirname "$0")" && pwd)"
version="$(cat "$here/VERSION")"
work="$(mktemp -d)"
mkdir -p "$work/classes"
(cd "$here" && find src/main/java -name '*.java' | LC_ALL=C sort) > "$work/sources"
(cd "$here" && javac --release 21 -encoding UTF-8 -proc:none -Xlint:all -Werror \
    -cp "$lib/main/*:$lib/boot/*" -d "$work/classes" @"$work/sources")
cp -R "$here/src/main/resources/." "$work/classes/"
# The decision table of the policy is checked before anything is packaged (not part of the jar).
mkdir -p "$work/check"
(cd "$here" && javac --release 21 -encoding UTF-8 -proc:none -Xlint:all -Werror \
    -cp "$work/classes" -d "$work/check" src/test/java/es/autotramita/keycloak/security/PolicyCheck.java)
java -cp "$work/classes:$work/check" es.autotramita.keycloak.security.PolicyCheck
printf 'Manifest-Version: 1.0\nCreated-By: autotramita build.sh\nImplementation-Title: autotramita-keycloak-security-provider\nImplementation-Version: %s\nBuilt-Against: Keycloak 26.8.2\n' "$version" > "$work/manifest"
(cd "$work/classes" && find . -type f | sed 's#^\./##' | LC_ALL=C sort > "$work/files")
(cd "$work/classes" && jar --create --file "$out" --manifest "$work/manifest" \
    --date=2026-11-25T00:00:00Z $(cat "$work/files"))
rm -rf "$work"
# The jar holds only this provider: its classes, service registrations, table changelog, page and
# messages. Anything else (a bundled library above all) stops the build.
jar --list --file "$out" | while read -r entry; do
    case "$entry" in
        META-INF/ | META-INF/MANIFEST.MF | META-INF/services/ | META-INF/autotramita-mfa-guard-changelog.xml) ;;
        META-INF/services/org.keycloak.authentication.RequiredActionFactory) ;;
        META-INF/services/org.keycloak.authentication.AuthenticatorFactory) ;;
        META-INF/services/org.keycloak.connections.jpa.entityprovider.JpaEntityProviderFactory) ;;
        META-INF/services/org.keycloak.services.resource.RealmResourceProviderFactory) ;;
        es/ | es/autotramita/ | es/autotramita/keycloak/ | es/autotramita/keycloak/security/) ;;
        es/autotramita/keycloak/security/*.class) ;;
        theme-resources/ | theme-resources/templates/ | theme-resources/messages/) ;;
        theme-resources/templates/at-disable-mfa.ftl | theme-resources/messages/messages_*.properties) ;;
        *) echo "unexpected jar entry: $entry" >&2; exit 1 ;;
    esac
done
sha256sum "$out"

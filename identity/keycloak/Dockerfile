# AutoTramita Keycloak image: the pinned upstream Keycloak plus one provider jar built from source
# against that image's own libraries. Nothing else is added. Build context: identity/keycloak.
ARG KEYCLOAK_IMAGE=quay.io/keycloak/keycloak:26.8.2@sha256:7e66a96e4739239070aeaf72e4c5decf0f7f682cfc725b9f7ea2b336eaba38b3
ARG JDK_IMAGE=eclipse-temurin:21-jdk@sha256:8ad118b146aa92da815b576441acd6b42b38236797ad0b6edc8c200b85bb0734

FROM ${KEYCLOAK_IMAGE} AS keycloak

FROM ${JDK_IMAGE} AS build
COPY --from=keycloak /opt/keycloak/lib/lib /keycloak-lib
COPY provider /provider
# Built twice: the two jars must be byte for byte the same (reproducible build).
RUN /provider/build.sh /keycloak-lib /first.jar \
    && /provider/build.sh /keycloak-lib /autotramita-keycloak-security-provider.jar \
    && cmp /first.jar /autotramita-keycloak-security-provider.jar

FROM ${KEYCLOAK_IMAGE}
COPY --from=build --chown=1000:0 --chmod=0444 /autotramita-keycloak-security-provider.jar /opt/keycloak/providers/autotramita-keycloak-security-provider.jar
USER 1000

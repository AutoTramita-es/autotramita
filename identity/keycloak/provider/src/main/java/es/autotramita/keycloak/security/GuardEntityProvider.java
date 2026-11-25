package es.autotramita.keycloak.security;

import java.util.List;
import org.keycloak.connections.jpa.entityprovider.JpaEntityProvider;

/** Registers {@link GuardEntity} and its table (Keycloak's supported custom-entity SPI). */
public final class GuardEntityProvider implements JpaEntityProvider {

    @Override
    public List<Class<?>> getEntities() {
        return List.of(GuardEntity.class);
    }

    @Override
    public String getChangelogLocation() {
        return "META-INF/autotramita-mfa-guard-changelog.xml";
    }

    @Override
    public String getFactoryId() {
        return GuardEntityProviderFactory.ID;
    }

    @Override
    public void close() {}
}

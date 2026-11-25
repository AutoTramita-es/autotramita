package es.autotramita.keycloak.security;

import java.util.List;
import org.keycloak.connections.jpa.entityprovider.JpaEntityProvider;

/** Registers {@link GuardEntity} and its table (Keycloak's supported custom-entity SPI). */
public final class GuardEntityProvider implements JpaEntityProvider {

    /**
     * Still abstract in Keycloak 26.8, but marked for removal: the Quarkus distribution finds the
     * entity in the provider jar at build time. Kept because the interface requires it.
     */
    @Override
    @SuppressWarnings("removal")
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

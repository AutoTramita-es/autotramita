package es.autotramita.keycloak.security;

import org.keycloak.Config;
import org.keycloak.connections.jpa.entityprovider.JpaEntityProvider;
import org.keycloak.connections.jpa.entityprovider.JpaEntityProviderFactory;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;

/** Factory of {@link GuardEntityProvider}. */
public final class GuardEntityProviderFactory implements JpaEntityProviderFactory {

    static final String ID = "autotramita-mfa-guard";

    @Override
    public JpaEntityProvider create(KeycloakSession session) {
        return new GuardEntityProvider();
    }

    @Override
    public void init(Config.Scope config) {}

    @Override
    public void postInit(KeycloakSessionFactory factory) {}

    @Override
    public void close() {}

    @Override
    public String getId() {
        return ID;
    }
}

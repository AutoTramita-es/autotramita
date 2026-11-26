package es.autotramita.keycloak.security;

import java.util.Map;
import org.keycloak.Config;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.provider.ServerInfoAwareProviderFactory;
import org.keycloak.services.resource.RealmResourceProvider;
import org.keycloak.services.resource.RealmResourceProviderFactory;

/** Registers {@link SecurityResource} under {@code /realms/{realm}/at-security} (T10-REC OD-5). */
public final class SecurityResourceProviderFactory implements RealmResourceProviderFactory, ServerInfoAwareProviderFactory {

    public static final String ID = "at-security";

    @Override
    public RealmResourceProvider create(KeycloakSession session) {
        return new RealmResourceProvider() {
            @Override
            public Object getResource() {
                return new SecurityResource(session);
            }

            @Override
            public void close() {}
        };
    }

    @Override
    public String getId() {
        return ID;
    }

    @Override
    public void init(Config.Scope config) {}

    @Override
    public void postInit(KeycloakSessionFactory factory) {}

    @Override
    public void close() {}

    @Override
    public Map<String, String> getOperationalInfo() {
        return Map.of("autotramita-guard", GuardedActionFactory.VERSION);
    }
}

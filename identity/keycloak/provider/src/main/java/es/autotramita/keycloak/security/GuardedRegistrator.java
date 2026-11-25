package es.autotramita.keycloak.security;

import org.keycloak.authentication.CredentialRegistrator;
import org.keycloak.authentication.RequiredActionProvider;
import org.keycloak.models.KeycloakSession;
import org.keycloak.sessions.AuthenticationSessionModel;

/**
 * A guarded action that registers a credential. It keeps the built-in action's credential type, so
 * Keycloak still asks for the level that type belongs to before the action starts.
 */
public final class GuardedRegistrator extends GuardedAction implements CredentialRegistrator {

    GuardedRegistrator(String id, Policy.Change change, RequiredActionProvider delegate) {
        super(id, change, delegate);
    }

    @Override
    public String getCredentialType(KeycloakSession session, AuthenticationSessionModel authSession) {
        return ((CredentialRegistrator) delegate).getCredentialType(session, authSession);
    }
}

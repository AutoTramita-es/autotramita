package es.autotramita.keycloak.security;

import java.util.Map;
import org.keycloak.authentication.CredentialRegistrator;
import org.keycloak.authentication.RequiredActionProvider;
import org.keycloak.authentication.requiredactions.RecoveryAuthnCodesAction;
import org.keycloak.authentication.requiredactions.UpdatePassword;
import org.keycloak.authentication.requiredactions.UpdateTotp;
import org.keycloak.authentication.requiredactions.WebAuthnPasswordlessRegisterFactory;
import org.keycloak.authentication.requiredactions.WebAuthnRegisterFactory;
import org.keycloak.models.KeycloakSession;
import org.keycloak.provider.ServerInfoAwareProviderFactory;

/**
 * The guarded credential actions. Each factory extends the built-in one and registers under the
 * same provider ID: Keycloak prefers a custom factory to an internal one with the same ID
 * (ProviderManager.compareFactories), and its authenticators cast the factory of their set-up
 * action to the built-in class, so the subclass keeps every built-in behaviour and only wraps the
 * provider it creates. The order is raised too, so the choice does not rest on one rule.
 */
public final class GuardedActionFactory {

    static final String VERSION = "1.2.0";
    static final int ORDER = 100;

    private GuardedActionFactory() {}

    static RequiredActionProvider wrap(String id, Policy.Change change, RequiredActionProvider builtIn) {
        if (builtIn instanceof CredentialRegistrator) {
            return new GuardedRegistrator(id, change, builtIn);
        }
        return new GuardedAction(id, change, builtIn);
    }

    static Map<String, String> info(Policy.Change change) {
        return Map.of("autotramita-guard", VERSION, "change", change.name());
    }

    /** CONFIGURE_TOTP. */
    public static final class Totp extends UpdateTotp implements ServerInfoAwareProviderFactory {
        @Override
        public RequiredActionProvider create(KeycloakSession session) {
            return wrap(getId(), Policy.Change.PERMANENT_FACTOR, super.create(session));
        }

        @Override
        public int order() {
            return ORDER;
        }

        @Override
        public Map<String, String> getOperationalInfo() {
            return info(Policy.Change.PERMANENT_FACTOR);
        }
    }

    /** webauthn-register. */
    public static final class Passkey extends WebAuthnRegisterFactory implements ServerInfoAwareProviderFactory {
        @Override
        public RequiredActionProvider create(KeycloakSession session) {
            return wrap(getId(), Policy.Change.PERMANENT_FACTOR, super.create(session));
        }

        @Override
        public int order() {
            return ORDER;
        }

        @Override
        public Map<String, String> getOperationalInfo() {
            return info(Policy.Change.PERMANENT_FACTOR);
        }
    }

    /** webauthn-register-passwordless. */
    public static final class PasswordlessPasskey extends WebAuthnPasswordlessRegisterFactory
            implements ServerInfoAwareProviderFactory {
        @Override
        public RequiredActionProvider create(KeycloakSession session) {
            return wrap(getId(), Policy.Change.PERMANENT_FACTOR, super.create(session));
        }

        @Override
        public int order() {
            return ORDER;
        }

        @Override
        public Map<String, String> getOperationalInfo() {
            return info(Policy.Change.PERMANENT_FACTOR);
        }
    }

    /** CONFIGURE_RECOVERY_AUTHN_CODES. */
    public static final class RecoveryCodes extends RecoveryAuthnCodesAction implements ServerInfoAwareProviderFactory {
        @Override
        public RequiredActionProvider create(KeycloakSession session) {
            return wrap(getId(), Policy.Change.RECOVERY_CODES, super.create(session));
        }

        @Override
        public int order() {
            return ORDER;
        }

        @Override
        public Map<String, String> getOperationalInfo() {
            return info(Policy.Change.RECOVERY_CODES);
        }
    }

    /** UPDATE_PASSWORD. */
    public static final class Password extends UpdatePassword implements ServerInfoAwareProviderFactory {
        @Override
        public RequiredActionProvider create(KeycloakSession session) {
            return wrap(getId(), Policy.Change.PASSWORD, super.create(session));
        }

        @Override
        public int order() {
            return ORDER;
        }

        @Override
        public Map<String, String> getOperationalInfo() {
            return info(Policy.Change.PASSWORD);
        }
    }
}

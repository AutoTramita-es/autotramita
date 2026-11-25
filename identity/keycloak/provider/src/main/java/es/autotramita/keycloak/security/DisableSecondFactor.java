package es.autotramita.keycloak.security;

import jakarta.ws.rs.core.MultivaluedMap;
import java.util.List;
import java.util.Map;
import org.keycloak.Config;
import org.keycloak.authentication.AuthenticatorUtil;
import org.keycloak.authentication.InitiatedActionSupport;
import org.keycloak.authentication.RequiredActionContext;
import org.keycloak.authentication.RequiredActionFactory;
import org.keycloak.authentication.RequiredActionProvider;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.provider.ProviderConfigProperty;
import org.keycloak.provider.ServerInfoAwareProviderFactory;

/**
 * The controlled switch-off of the second factor ({@code kc_action=at-disable-mfa}, started by the
 * application). It needs a permanent factor proven in this fresh sign-in and the person's explicit
 * confirmation; then, under the guard lock and in one transaction, every permanent factor and
 * recovery code is removed, the obligation is lifted and every other session of the person ends.
 */
public final class DisableSecondFactor implements RequiredActionProvider, RequiredActionFactory, ServerInfoAwareProviderFactory {

    public static final String ID = "at-disable-mfa";
    static final String CONFIRMATION = "DISABLE_MFA";

    @Override
    public InitiatedActionSupport initiatedActionSupport() {
        return InitiatedActionSupport.SUPPORTED;
    }

    @Override
    public void evaluateTriggers(RequiredActionContext context) {}

    @Override
    public void requiredActionChallenge(RequiredActionContext context) {
        Guard state = Guard.peek(context.getSession(), context.getAuthenticationSession());
        String refusal = state.refusal(Policy.Change.DISABLE);
        if (refusal != null) {
            GuardedAction.refuse(context, state, refusal, ID);
            return;
        }
        context.challenge(context.form().createForm("at-disable-mfa.ftl"));
    }

    @Override
    public void processAction(RequiredActionContext context) {
        MultivaluedMap<String, String> form = context.getHttpRequest().getDecodedFormParameters();
        if (!CONFIRMATION.equals(form.getFirst("confirm"))) {
            requiredActionChallenge(context);
            return;
        }
        Guard state = Guard.lock(context.getSession(), context.getAuthenticationSession());
        String refusal = state.refusal(Policy.Change.DISABLE);
        if (refusal != null) {
            GuardedAction.refuse(context, state, refusal, ID);
            return;
        }
        state.disable();
        AuthenticatorUtil.logoutOtherSessions(context);
        context.success();
    }

    @Override
    public RequiredActionProvider create(KeycloakSession session) {
        return this;
    }

    @Override
    public String getId() {
        return ID;
    }

    @Override
    public String getDisplayText() {
        return "AutoTramita: switch the second factor off";
    }

    @Override
    public boolean isOneTimeAction() {
        return true;
    }

    @Override
    public List<ProviderConfigProperty> getConfigMetadata() {
        return RequiredActionFactory.super.getConfigMetadata();
    }

    @Override
    public void init(Config.Scope config) {}

    @Override
    public void postInit(KeycloakSessionFactory factory) {}

    @Override
    public void close() {}

    @Override
    public Map<String, String> getOperationalInfo() {
        return Map.of("autotramita-guard", GuardedActionFactory.VERSION, "change", Policy.Change.DISABLE.name());
    }
}

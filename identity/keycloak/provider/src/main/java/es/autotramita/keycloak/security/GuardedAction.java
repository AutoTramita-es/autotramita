package es.autotramita.keycloak.security;

import org.jboss.logging.Logger;
import org.keycloak.authentication.InitiatedActionSupport;
import org.keycloak.authentication.RequiredActionContext;
import org.keycloak.authentication.RequiredActionProvider;
import org.keycloak.events.EventType;
import org.keycloak.models.KeycloakSession;
import org.keycloak.sessions.AuthenticationSessionModel;

/**
 * A built-in required action that changes a credential, run only when the AutoTramita policy
 * allows the change for the account as it is at that moment and the proof of this authentication.
 *
 * <p>The decision is taken twice: before the form is shown (a refusal there spares the person a
 * form they cannot use) and, authoritatively, when the form is submitted: under the person's lock,
 * on freshly read state, in the same transaction as the change itself.
 */
public class GuardedAction implements RequiredActionProvider {

    private static final Logger LOG = Logger.getLogger(GuardedAction.class);

    protected final RequiredActionProvider delegate;
    private final String id;
    private final Policy.Change change;

    GuardedAction(String id, Policy.Change change, RequiredActionProvider delegate) {
        this.id = id;
        this.change = change;
        this.delegate = delegate;
    }

    @Override
    public InitiatedActionSupport initiatedActionSupport() {
        return delegate.initiatedActionSupport();
    }

    @Override
    public void initiatedActionCanceled(KeycloakSession session, AuthenticationSessionModel authSession) {
        delegate.initiatedActionCanceled(session, authSession);
    }

    @Override
    public void evaluateTriggers(RequiredActionContext context) {
        delegate.evaluateTriggers(context);
    }

    @Override
    public int getMaxAuthAge(KeycloakSession session) {
        return delegate.getMaxAuthAge(session);
    }

    @Override
    public void requiredActionChallenge(RequiredActionContext context) {
        Guard state = Guard.peek(context.getSession(), context.getAuthenticationSession());
        String refusal = state.refusal(change);
        if (refusal != null) {
            refuse(context, state, refusal, id);
            return;
        }
        delegate.requiredActionChallenge(context);
    }

    @Override
    public void processAction(RequiredActionContext context) {
        Guard state = Guard.lock(context.getSession(), context.getAuthenticationSession());
        String refusal = state.refusal(change);
        if (refusal != null) {
            refuse(context, state, refusal, id);
            return;
        }
        delegate.processAction(context);
        if (context.getStatus() == RequiredActionContext.Status.SUCCESS) {
            state.changed(change);
        }
    }

    static void refuse(RequiredActionContext context, Guard state, String reason, String id) {
        LOG.warnf(
                "credential change refused: action=%s reason=%s realm=%s user=%s",
                id, reason, state.realmName(), state.userId());
        context.getEvent()
                .clone()
                .event(EventType.CUSTOM_REQUIRED_ACTION_ERROR)
                .detail("custom_required_action", id)
                .detail("reason", reason)
                .error("credential_change_refused");
        context.failure(reason);
    }

    @Override
    public void close() {
        delegate.close();
    }
}

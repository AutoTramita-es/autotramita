package es.autotramita.keycloak.security;

import jakarta.ws.rs.DELETE;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import java.util.Map;
import org.jboss.logging.Logger;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.UserModel;
import org.keycloak.representations.AccessToken;
import org.keycloak.services.managers.AppAuthManager;
import org.keycloak.services.managers.AuthenticationManager;
import org.keycloak.storage.UserStoragePrivateUtil;

/**
 * Two changes the application asks for that must be decided under the person's guard lock
 * (T10-REC OD-5), so that they are serialised with the switch-off and every guarded credential
 * change on every node sharing the database:
 *
 * <ul>
 *   <li>{@code POST /realms/{realm}/at-security/users/{id}/mandatory} marks the account
 *       {@code at_mfa_mandatory} and {@code at_mfa_required}, only while it holds a permanent factor
 *       (200 {@code {"marked":true}}, otherwise 409 {@code {"reason":"permanent_factor_missing"}}).
 *       Only these two attributes are written; nothing else of the person changes.</li>
 *   <li>{@code DELETE /realms/{realm}/at-security/users/{id}/credentials/{credentialId}} removes one
 *       second factor, unless the account would be left without a permanent factor while recovery
 *       codes remain or while it is obliged or mandatory (204, 404, or 409
 *       {@code {"reason":"last_permanent_factor"}}).</li>
 * </ul>
 *
 * <p>Callers: the realm's own service account of the application ({@code at-admin-svc}), with the
 * {@code manage-users} role of {@code realm-management} in a valid token of this realm. Anything
 * else is 401/403 before the person is even looked up.
 */
public final class SecurityResource {

    private static final Logger LOG = Logger.getLogger(SecurityResource.class);
    private static final String MANAGEMENT = "realm-management";
    private static final String ROLE = "manage-users";

    private final KeycloakSession session;

    SecurityResource(KeycloakSession session) {
        this.session = session;
    }

    @SuppressWarnings("removal")
    private Response authorise() {
        AuthenticationManager.AuthResult auth = new AppAuthManager.BearerTokenAuthenticator(session).authenticate();
        if (auth == null) {
            return Response.status(Response.Status.UNAUTHORIZED).build();
        }
        AccessToken token = auth.getToken();
        AccessToken.Access access = token == null ? null : token.getResourceAccess(MANAGEMENT);
        if (access == null || !access.isUserInRole(ROLE)) {
            return Response.status(Response.Status.FORBIDDEN).build();
        }
        return null;
    }

    private UserModel person(RealmModel realm, String id) {
        return UserStoragePrivateUtil.userLocalStorage(session).getUserById(realm, id);
    }

    @POST
    @Path("users/{id}/mandatory")
    @Produces(MediaType.APPLICATION_JSON)
    public Response mandatory(@PathParam("id") String id) {
        Response refused = authorise();
        if (refused != null) {
            return refused;
        }
        RealmModel realm = session.getContext().getRealm();
        UserModel found = person(realm, id);
        if (found == null) {
            return Response.status(Response.Status.NOT_FOUND).build();
        }
        Guard state = Guard.lockForAdministration(session, realm, found);
        if (!state.markMandatory()) {
            LOG.infof("at-security mandatory refused realm=%s user=%s reason=permanent_factor_missing",
                    realm.getName(), state.userId());
            return Response.status(Response.Status.CONFLICT).entity(Map.of("reason", "permanent_factor_missing")).build();
        }
        LOG.infof("at-security mandatory set realm=%s user=%s", realm.getName(), state.userId());
        return Response.ok(Map.of("marked", true)).build();
    }

    @DELETE
    @Path("users/{id}/credentials/{credentialId}")
    @Produces(MediaType.APPLICATION_JSON)
    public Response removeSecondFactor(@PathParam("id") String id, @PathParam("credentialId") String credentialId) {
        Response refused = authorise();
        if (refused != null) {
            return refused;
        }
        RealmModel realm = session.getContext().getRealm();
        UserModel found = person(realm, id);
        if (found == null) {
            return Response.status(Response.Status.NOT_FOUND).build();
        }
        Guard state = Guard.lockForAdministration(session, realm, found);
        switch (state.removeSecondFactor(credentialId)) {
            case REMOVED:
                return Response.noContent().build();
            case LAST_PERMANENT_FACTOR:
                return Response.status(Response.Status.CONFLICT).entity(Map.of("reason", "last_permanent_factor")).build();
            default:
                return Response.status(Response.Status.NOT_FOUND).build();
        }
    }
}

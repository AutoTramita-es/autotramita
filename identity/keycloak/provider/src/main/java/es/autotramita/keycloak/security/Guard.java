package es.autotramita.keycloak.security;

import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import org.keycloak.authentication.AuthenticatorUtil;
import org.keycloak.common.util.Time;
import org.keycloak.connections.jpa.JpaConnectionProvider;
import org.keycloak.credential.CredentialModel;
import org.keycloak.models.DefaultActionTokenKey;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.UserModel;
import org.keycloak.models.cache.UserCache;
import org.keycloak.sessions.AuthenticationSessionModel;
import org.keycloak.storage.UserStoragePrivateUtil;

/**
 * Reads the state the policy needs and serialises guarded changes of one person.
 *
 * <p>The lock is a pessimistic row lock on {@link GuardEntity} in the request's own database
 * transaction, so it holds across Keycloak instances that share the database and is released only
 * when the credential change commits or rolls back. After taking it, the person is evicted from the
 * user cache and read again from the database: a change committed by another instance just before
 * is seen.
 */
final class Guard {

    /** Realm attribute: the account must never fall back to the password alone. */
    static final String OBLIGATION = "at_mfa_required";

    /** Realm attribute: a policy forbids switching the second factor off (set by T10). */
    static final String MANDATORY = "at_mfa_mandatory";

    /** Authentication-session note: when the interactive sign-in of this session started. */
    static final String STARTED = "at.guard.started";

    /** Authentication-session note: the permanent factor this session set up. */
    static final String ENROLLED = "at.guard.enrolled";

    private static final Map<String, Object> LOCK_TIMEOUT =
            Map.of("jakarta.persistence.lock.timeout", 10_000);

    private final KeycloakSession session;
    private final RealmModel realm;
    private final AuthenticationSessionModel authSession;
    private final UserModel user;
    private final GuardEntity row;
    private final Set<String> permanentBefore;

    private Guard(
            KeycloakSession session,
            RealmModel realm,
            AuthenticationSessionModel authSession,
            UserModel user,
            GuardEntity row) {
        this.session = session;
        this.realm = realm;
        this.authSession = authSession;
        this.user = user;
        this.row = row;
        this.permanentBefore = permanentIds(user);
    }

    /** The state without taking the lock (used before a form is shown). */
    static Guard peek(KeycloakSession session, AuthenticationSessionModel authSession) {
        RealmModel realm = authSession.getRealm();
        UserModel user = fresh(session, realm, authSession.getAuthenticatedUser());
        return new Guard(session, realm, authSession, user, null);
    }

    /** Take the person's lock, then read the state again. Any failure propagates (fail closed). */
    static Guard lock(KeycloakSession session, AuthenticationSessionModel authSession) {
        RealmModel realm = authSession.getRealm();
        UserModel authenticated = authSession.getAuthenticatedUser();
        if (authenticated == null) {
            throw new IllegalStateException("no authenticated user");
        }
        EntityManager em = session.getProvider(JpaConnectionProvider.class).getEntityManager();
        GuardEntity row =
                em.find(GuardEntity.class, authenticated.getId(), LockModeType.PESSIMISTIC_WRITE, LOCK_TIMEOUT);
        if (row == null) {
            // A concurrent first insert of the same person fails on the primary key: fail closed.
            row = new GuardEntity(authenticated.getId(), realm.getId());
            em.persist(row);
            em.flush();
        }
        UserModel user = fresh(session, realm, authenticated);
        return new Guard(session, realm, authSession, user, row);
    }

    private static UserModel fresh(KeycloakSession session, RealmModel realm, UserModel user) {
        if (user == null) {
            throw new IllegalStateException("no authenticated user");
        }
        UserCache cache = session.getProvider(UserCache.class);
        if (cache != null) {
            cache.evict(realm, user);
        }
        UserModel stored = UserStoragePrivateUtil.userLocalStorage(session).getUserById(realm, user.getId());
        if (stored == null || !stored.isEnabled()) {
            throw new IllegalStateException("user not found or disabled");
        }
        return stored;
    }

    private static Set<String> permanentIds(UserModel user) {
        return user.credentialManager()
                .getStoredCredentialsStream()
                .filter(c -> Policy.PERMANENT.contains(c.getType()))
                .map(CredentialModel::getId)
                .collect(Collectors.toSet());
    }

    Policy.Account account() {
        Set<String> types = user.credentialManager()
                .getStoredCredentialsStream()
                .map(CredentialModel::getType)
                .collect(Collectors.toSet());
        boolean permanent = types.stream().anyMatch(Policy.PERMANENT::contains);
        boolean obliged = "true".equals(user.getFirstAttribute(OBLIGATION));
        boolean mandatory = "true".equals(user.getFirstAttribute(MANDATORY));
        return new Policy.Account(permanent, types.contains(Policy.RECOVERY_CODES), obliged, mandatory);
    }

    Policy.Proof proof() {
        List<String> used = AuthenticatorUtil.getAuthnCredentials(authSession);
        boolean permanent = used.stream().anyMatch(Policy.PERMANENT::contains);
        boolean code = used.contains(Policy.RECOVERY_CODES);
        String started = authSession.getAuthNote(STARTED);
        boolean fresh = false;
        if (started != null) {
            try {
                fresh = Time.currentTime() - Integer.parseInt(started) <= Policy.FRESH_SECONDS;
            } catch (NumberFormatException e) {
                fresh = false;
            }
        }
        boolean emailLink = user.getId().equals(authSession.getAuthNote(DefaultActionTokenKey.ACTION_TOKEN_USER_ID));
        String enrolled = authSession.getAuthNote(ENROLLED);
        boolean enrolledHere = enrolled != null && permanentBefore.contains(enrolled);
        return new Policy.Proof(permanent, code, fresh, emailLink, enrolledHere);
    }

    String refusal(Policy.Change change) {
        return Policy.refusal(change, account(), proof());
    }

    /**
     * After a successful change, still under the lock and in the same transaction: count it and,
     * when the person now holds a permanent factor, record the permanent obligation.
     */
    void changed(Policy.Change change) {
        if (row == null) {
            throw new IllegalStateException("change recorded without the lock");
        }
        row.recordChange();
        Set<String> after = permanentIds(user);
        Set<String> added = new HashSet<>(after);
        added.removeAll(permanentBefore);
        if (change == Policy.Change.PERMANENT_FACTOR && !added.isEmpty()) {
            authSession.setAuthNote(ENROLLED, added.iterator().next());
        }
        if (!after.isEmpty() && !"true".equals(user.getFirstAttribute(OBLIGATION))) {
            user.setSingleAttribute(OBLIGATION, "true");
        }
    }

    /**
     * Switch the second factor off, under the lock and in one transaction: every permanent factor
     * and recovery code is removed and the obligation is lifted only together with them.
     */
    void disable() {
        if (row == null) {
            throw new IllegalStateException("change recorded without the lock");
        }
        List<String> doomed = user.credentialManager()
                .getStoredCredentialsStream()
                .filter(c -> Policy.PERMANENT.contains(c.getType()) || Policy.RECOVERY_CODES.equals(c.getType()))
                .map(CredentialModel::getId)
                .toList();
        for (String id : doomed) {
            if (!user.credentialManager().removeStoredCredentialById(id)) {
                throw new IllegalStateException("a credential could not be removed");
            }
        }
        user.removeAttribute(OBLIGATION);
        row.recordChange();
    }

    String userId() {
        return user.getId();
    }

    String realmName() {
        return realm.getName();
    }

    KeycloakSession session() {
        return session;
    }
}

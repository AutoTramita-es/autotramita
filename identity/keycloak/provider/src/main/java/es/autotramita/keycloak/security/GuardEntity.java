package es.autotramita.keycloak.security;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One row per person whose credentials were changed through a guarded action. Its database row
 * lock serialises guarded changes of that person across every Keycloak instance sharing the
 * database; the counter records each change.
 */
@Entity
@Table(name = "AT_MFA_GUARD")
public class GuardEntity {

    @Id
    @Column(name = "USER_ID", length = 255, nullable = false)
    private String userId;

    @Column(name = "REALM_ID", length = 255, nullable = false)
    private String realmId;

    @Column(name = "CHANGES", nullable = false)
    private long changes;

    protected GuardEntity() {}

    GuardEntity(String userId, String realmId) {
        this.userId = userId;
        this.realmId = realmId;
    }

    String getUserId() {
        return userId;
    }

    String getRealmId() {
        return realmId;
    }

    long getChanges() {
        return changes;
    }

    void recordChange() {
        changes++;
    }
}

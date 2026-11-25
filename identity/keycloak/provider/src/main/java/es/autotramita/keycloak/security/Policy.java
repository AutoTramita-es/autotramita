package es.autotramita.keycloak.security;

import java.util.Set;

/**
 * The credential-change policy of the AutoTramita final MFA decision (2026-11-25). Pure logic
 * without Keycloak types, so that every rule is visible in one place.
 */
public final class Policy {

    /** Second factors that can be used again and again. */
    public static final Set<String> PERMANENT = Set.of("otp", "webauthn", "webauthn-passwordless");

    /** The backup of a permanent factor. */
    public static final String RECOVERY_CODES = "recovery-authn-codes";

    /** A proof older than this is not fresh (D23: ten minutes). */
    public static final int FRESH_SECONDS = 600;

    /** The kind of credential a required action changes. */
    public enum Change {
        PERMANENT_FACTOR,
        RECOVERY_CODES,
        PASSWORD,
        /** Switching the second factor off: every permanent factor and recovery code goes. */
        DISABLE
    }

    /**
     * What the account holds now, read under the guard lock.
     *
     * @param permanent at least one one-time code or passkey
     * @param codes a set of recovery codes
     * @param obliged the account must never fall back to the password alone
     * @param mandatory a policy (platform grants, T10) forbids switching the second factor off
     */
    public record Account(boolean permanent, boolean codes, boolean obliged, boolean mandatory) {}

    /**
     * What this authentication session proved.
     *
     * @param permanent a one-time code or passkey was verified in it
     * @param code a recovery code was verified in it
     * @param fresh the interactive sign-in started at most {@link #FRESH_SECONDS} ago
     * @param emailLink it was started by an e-mail action token of this person
     * @param enrolledHere this session set up the permanent factor the account holds
     */
    public record Proof(
            boolean permanent, boolean code, boolean fresh, boolean emailLink, boolean enrolledHere) {}

    private Policy() {}

    /** {@code null} when the change is allowed, otherwise a reason code (never a secret). */
    public static String refusal(Change change, Account account, Proof proof) {
        boolean locked = account.obliged() && !account.permanent() && !account.codes();
        boolean permanentProof = proof.permanent() && proof.fresh();
        switch (change) {
            case PERMANENT_FACTOR:
                if (proof.emailLink()) {
                    return "email_link_cannot_add_a_factor";
                }
                if (account.permanent()) {
                    return permanentProof ? null : "permanent_factor_required";
                }
                if (locked) {
                    return "account_locked";
                }
                if (account.codes() || account.obliged()) {
                    // recovery codes are no proof of a permanent factor: an account holding codes
                    // only waits for the controlled recovery (T10/T11)
                    return "controlled_recovery_required";
                }
                return null; // the first factor of a person who never had one (I07)
            case RECOVERY_CODES:
                if (proof.emailLink()) {
                    return "email_link_cannot_add_a_factor";
                }
                if (!account.permanent()) {
                    return locked ? "account_locked" : "permanent_factor_missing";
                }
                return permanentProof || proof.enrolledHere() ? null : "permanent_factor_required";
            case PASSWORD:
                if (proof.emailLink()) {
                    return null; // recovery of a forgotten password (D20): every factor stays
                }
                if (account.permanent() || account.codes() || account.obliged()) {
                    return permanentProof ? null : "permanent_factor_required";
                }
                return null;
            case DISABLE:
                if (proof.emailLink()) {
                    return "email_link_cannot_disable";
                }
                if (account.mandatory()) {
                    return "second_factor_mandatory";
                }
                if (!account.permanent()) {
                    return "permanent_factor_missing";
                }
                return permanentProof ? null : "permanent_factor_required";
            default:
                return "unknown_change";
        }
    }
}

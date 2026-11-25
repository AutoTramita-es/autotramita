package es.autotramita.keycloak.security;

import es.autotramita.keycloak.security.Policy.Account;
import es.autotramita.keycloak.security.Policy.Change;
import es.autotramita.keycloak.security.Policy.Proof;

/**
 * The decision table of {@link Policy}, checked on every build (no test library: the provider has
 * no dependency). Every combination of account state and proof is evaluated; the invariants below
 * must hold for all of them, and a few named cases pin the exact answers.
 */
public final class PolicyCheck {

    private static int checked;

    private PolicyCheck() {}

    public static void main(String[] args) {
        boolean[] both = {false, true};
        for (Change change : Change.values()) {
            for (boolean permanent : both) for (boolean codes : both) for (boolean obliged : both)
            for (boolean mandatory : both) for (boolean proofPermanent : both) for (boolean code : both)
            for (boolean fresh : both) for (boolean link : both) for (boolean here : both) {
                Account account = new Account(permanent, codes, obliged, mandatory);
                Proof proof = new Proof(proofPermanent, code, fresh, link, here);
                String refusal = Policy.refusal(change, account, proof);
                boolean allowed = refusal == null;
                boolean strongProof = proofPermanent && fresh;
                // Nothing is ever allowed on an account that has a permanent factor without a fresh
                // proof of one, except a password reset through the e-mail link and new codes right
                // after setting up the first factor in the same sign-in.
                if (allowed && permanent && !strongProof) {
                    require((change == Change.PASSWORD && link)
                            || (change == Change.RECOVERY_CODES && here), "downgrade", change, account, proof);
                }
                // An e-mail link never adds a factor and never switches it off.
                if (link && change != Change.PASSWORD) {
                    require(!allowed, "e-mail link", change, account, proof);
                }
                // A locked account (obliged, nothing left) gets no factor set up.
                if (obliged && !permanent && !codes && change != Change.PASSWORD) {
                    require(!allowed, "locked", change, account, proof);
                }
                // Recovery codes only ever follow a permanent factor.
                if (change == Change.RECOVERY_CODES && allowed) {
                    require(permanent, "codes without a permanent factor", change, account, proof);
                }
                // A mandatory second factor is never switched off; a recovery code never switches it off.
                if (change == Change.DISABLE && allowed) {
                    require(!mandatory && permanent && strongProof, "switch-off", change, account, proof);
                }
                // A password change of a protected account needs the permanent factor or the e-mail link.
                if (change == Change.PASSWORD && allowed && (permanent || codes || obliged)) {
                    require(strongProof || link, "password", change, account, proof);
                }
                checked++;
            }
        }
        Proof none = new Proof(false, false, false, false, false);
        Proof otp = new Proof(true, false, true, false, false);
        Proof code = new Proof(false, true, true, false, false);
        Account fresh = new Account(false, false, false, false);
        Account totp = new Account(true, false, true, false);
        Account codesOnly = new Account(false, true, true, false);
        require(Policy.refusal(Change.PERMANENT_FACTOR, fresh, none) == null, "first factor", null, fresh, none);
        require("permanent_factor_required".equals(Policy.refusal(Change.PERMANENT_FACTOR, totp, none)),
                "F-1R-C", null, totp, none);
        require("permanent_factor_required".equals(Policy.refusal(Change.PASSWORD, totp, none)),
                "F-3K", null, totp, none);
        require("permanent_factor_required".equals(Policy.refusal(Change.RECOVERY_CODES, totp, code)),
                "held code", null, totp, code);
        require(Policy.refusal(Change.PERMANENT_FACTOR, codesOnly, code) == null, "transition", null, codesOnly, code);
        require(Policy.refusal(Change.DISABLE, totp, otp) == null, "switch-off", null, totp, otp);
        require(Policy.refusal(Change.DISABLE, totp, code) != null, "switch-off by code", null, totp, code);
        System.out.println("PolicyCheck: " + checked + " combinations, all invariants hold");
    }

    private static void require(boolean condition, String rule, Change change, Account account, Proof proof) {
        if (!condition) {
            throw new AssertionError(rule + " violated: " + change + " " + account + " " + proof);
        }
    }
}

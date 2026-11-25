"""Let a reviewed D37 operation leave MANUAL_REVIEW (F2-T09-REC F-4).

Revision ID: 0009
Revises: 0008

Only the transition rule of the existing guard changes. A held operation may go back to the
recovery worker (``APPLYING``, unclaimed) or be cancelled, and only inside a transaction that
names this very operation in ``app.email_change_review``. That setting protects against an
accidental write (the periodic sweep never sets it); it is not an authorisation boundary. Who
may resolve is decided by the application (``app.auth.security.email_change_review``), and no
role gets a new privilege here.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_REVIEW = """
                OR (OLD.status = 'MANUAL_REVIEW' AND NEW.status IN ('APPLYING','CANCELLED')
                    AND NEW.lease_id IS NULL
                    AND coalesce(current_setting('app.email_change_review', true), '')
                        = OLD.id::text)"""


def _guard(extra: str) -> str:
    """The body of ``email_change_guard`` exactly as 0007 created it, plus ``extra``."""
    return f"""
        CREATE OR REPLACE FUNCTION email_change_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.session_id IS DISTINCT FROM OLD.session_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'immutable email change identity' USING ERRCODE = '23514';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'PENDING' AND NEW.status IN ('CONFIRMED','CANCELLED','EXPIRED'))
                OR (OLD.status = 'CONFIRMED' AND NEW.status IN ('APPLYING','MANUAL_REVIEW'))
                OR (OLD.status = 'APPLYING' AND NEW.status IN ('COMPLETED','MANUAL_REVIEW')){extra}
            ) THEN
                RAISE EXCEPTION 'invalid email change transition' USING ERRCODE = '23514';
            END IF;
            IF (
                NEW.new_email IS DISTINCT FROM OLD.new_email OR
                NEW.new_email_normalized IS DISTINCT FROM OLD.new_email_normalized OR
                NEW.old_email IS DISTINCT FROM OLD.old_email
            ) AND NOT (NEW.status IN ('COMPLETED', 'CANCELLED', 'EXPIRED')
                AND NEW.old_email IS NULL AND NEW.new_email IS NULL
                AND NEW.new_email_normalized IS NULL) THEN
                RAISE EXCEPTION 'confirmed addresses are immutable' USING ERRCODE = '23514';
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END $$
    """


def upgrade() -> None:
    op.execute(_guard(_REVIEW))


def downgrade() -> None:
    op.execute(_guard(""))

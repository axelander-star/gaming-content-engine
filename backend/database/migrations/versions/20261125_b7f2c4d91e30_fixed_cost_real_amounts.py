"""fixed cost real amounts

Sets the operator's real amounts (25.11.2026) on the seeded starting items, but
only where they still carry the original placeholder values, so own edits stay.

Revision ID: b7f2c4d91e30
Revises: 7433e2700ebb
Create Date: 2026-11-25 13:10:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'b7f2c4d91e30'
down_revision: str | None = '7433e2700ebb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE fixed_costs SET amount = 5.97, note = 'Jahrespreis laut INWX', updated_at = now() "
        "WHERE name = 'Domain kanalfabrik.de' AND amount = 0 AND interval = 'year'"
    )
    op.execute(
        "UPDATE fixed_costs SET amount = 21.42, currency = 'EUR', "
        "note = 'Persönliches Abo, Betrag laut Abbuchung inkl. MwSt.; kein API-Zugang für die "
        "Engine', updated_at = now() "
        "WHERE name = 'Claude Pro (Chat-Abo)' AND amount = 20 AND currency = 'USD'"
    )


def downgrade() -> None:
    # Data correction only; the previous placeholder values are not restored.
    pass

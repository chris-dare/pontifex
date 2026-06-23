"""rename schema core → pontifex_mcp_core

Revision ID: core_0004b
Revises: core_0004
Create Date: 2026-06-23

Bridges environments that were provisioned before ec55a7a renamed the
package schema from 'core' to 'pontifex_mcp_core'. Fresh databases
already have 'pontifex_mcp_core' (created by core_0001), so this is a
conditional no-op for them.
"""

from alembic import op

revision = "core_0004b"
down_revision = "core_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'core'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'pontifex_mcp_core'
            ) THEN
                EXECUTE 'ALTER SCHEMA core RENAME TO pontifex_mcp_core';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'pontifex_mcp_core'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'core'
            ) THEN
                EXECUTE 'ALTER SCHEMA pontifex_mcp_core RENAME TO core';
            END IF;
        END $$;
    """)

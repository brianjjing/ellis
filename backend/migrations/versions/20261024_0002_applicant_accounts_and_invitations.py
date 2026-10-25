"""applicant accounts and invitations

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24 18:31:56.148209
"""

from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('account',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.String(length=300), nullable=False),
    sa.Column('active_case_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('invitation',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('invited_by', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invitation_clinic_id'), 'invitation', ['clinic_id'], unique=False)
    op.create_index(op.f('ix_invitation_email'), 'invitation', ['email'], unique=False)
    op.add_column('cases', sa.Column('account_id', sa.String(length=40), nullable=True))
    op.create_index(op.f('ix_cases_account_id'), 'cases', ['account_id'], unique=False)
    op.create_foreign_key('cases_account_id_fkey', 'cases', 'account', ['account_id'], ['id'])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Same lockdown as 0001: hidden from Supabase's Data API roles; the Case API connects as the owner.
        supabase_roles = bind.execute(sa.text(
            "select count(*) from pg_roles where rolname in ('anon', 'authenticated')")).scalar() == 2
        for table in ("account", "invitation"):
            op.execute(f'alter table "{table}" enable row level security')
            if supabase_roles:
                op.execute(f'revoke all on "{table}" from anon, authenticated')


def downgrade() -> None:
    op.drop_constraint("cases_account_id_fkey", 'cases', type_='foreignkey')
    op.drop_index(op.f('ix_cases_account_id'), table_name='cases')
    op.drop_column('cases', 'account_id')
    op.drop_index(op.f('ix_invitation_email'), table_name='invitation')
    op.drop_index(op.f('ix_invitation_clinic_id'), table_name='invitation')
    op.drop_table('invitation')
    op.drop_table('account')

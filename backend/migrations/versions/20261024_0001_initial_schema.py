"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-24 12:51:19.657179
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

TABLES = ['agent_run', 'clinic', 'event', 'jobs', 'vault_value', 'staff_user', 'cases', 'briefing', 'case_link', 'deadline', 'derived', 'document', 'fact', 'flag', 'gap', 'memo', 'packet', 'review_item', 'session', 'signoff', 'task', 'utterance', 'extraction']


def _postgres_extras() -> None:
    # NOTIFY case_events on every event insert (LISTEN case_events for cross-process consumers).
    op.execute("""
        create or replace function notify_event() returns trigger as $$
        begin
          perform pg_notify('case_events', json_build_object(
            'case', new.case_id, 'kind', new.kind, 'id', new.id)::text);
          return new;
        end $$ language plpgsql
    """)
    op.execute("create trigger t_notify after insert on event for each row execute function notify_event()")
    # The event log is append-only. The app connects as the table owner, so a REVOKE would not bind it; a
    # trigger does. (DROP and TRUNCATE, used by seed resets, are unaffected.)
    op.execute("""
        create or replace function event_append_only() returns trigger as $$
        begin
          raise exception 'event is append-only';
        end $$ language plpgsql
    """)
    op.execute("create trigger t_append_only before update or delete on event "
               "for each row execute function event_append_only()")
    # Supabase exposes the public schema through its Data API. RLS with no policies hides every row from the
    # anon/authenticated roles; the Case API connects as the owner and is unaffected.
    supabase_roles = op.get_bind().execute(sa.text(
        "select count(*) from pg_roles where rolname in ('anon', 'authenticated')")).scalar() == 2
    for table in [*TABLES, "alembic_version"]:
        op.execute(f'alter table "{table}" enable row level security')
        if supabase_roles:
            op.execute(f'revoke all on "{table}" from anon, authenticated')


def upgrade() -> None:
    op.create_table('agent_run',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('agent', sa.String(length=40), nullable=False),
    sa.Column('backend', sa.String(length=20), nullable=False),
    sa.Column('trigger_events', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=True),
    sa.Column('prompt_version', sa.String(length=40), nullable=True),
    sa.Column('input_hash', sa.String(length=40), nullable=True),
    sa.Column('output', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('accepted_items', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('rejected_items', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('ms', sa.Integer(), nullable=True),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_run_case_id'), 'agent_run', ['case_id'], unique=False)
    op.create_index(op.f('ix_agent_run_clinic_id'), 'agent_run', ['clinic_id'], unique=False)
    op.create_table('clinic',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('settings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('event',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=True),
    sa.Column('case_id', sa.String(length=40), nullable=True),
    sa.Column('kind', sa.String(length=60), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('actor_type', sa.String(length=20), nullable=False),
    sa.Column('actor', sa.String(length=80), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_event_case_id'), 'event', ['case_id'], unique=False)
    op.create_index(op.f('ix_event_clinic_id'), 'event', ['clinic_id'], unique=False)
    op.create_index(op.f('ix_event_kind'), 'event', ['kind'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('agent', sa.String(length=40), nullable=False),
    sa.Column('trigger_event', sa.Integer(), nullable=True),
    sa.Column('trigger_events', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('run_id', sa.String(length=40), nullable=True),
    sa.Column('not_before', sa.DateTime(timezone=True), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id')
    )
    op.create_index(op.f('ix_jobs_agent'), 'jobs', ['agent'], unique=False)
    op.create_index(op.f('ix_jobs_case_id'), 'jobs', ['case_id'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_table('vault_value',
    sa.Column('fact_id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('field', sa.String(length=120), nullable=False),
    sa.Column('ciphertext', sa.Text(), nullable=False),
    sa.Column('last4', sa.String(length=8), nullable=True),
    sa.PrimaryKeyConstraint('fact_id')
    )
    op.create_index(op.f('ix_vault_value_case_id'), 'vault_value', ['case_id'], unique=False)
    op.create_index(op.f('ix_vault_value_clinic_id'), 'vault_value', ['clinic_id'], unique=False)
    op.create_table('staff_user',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('password_hash', sa.String(length=300), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_staff_user_clinic_id'), 'staff_user', ['clinic_id'], unique=False)
    op.create_table('cases',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('first_name', sa.String(length=100), nullable=False),
    sa.Column('last_name', sa.String(length=100), nullable=False),
    sa.Column('phone', sa.String(length=40), nullable=True),
    sa.Column('language', sa.String(length=10), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('sub_mode', sa.String(length=30), nullable=True),
    sa.Column('settings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('assigned_reviewer', sa.String(length=40), nullable=True),
    sa.Column('disclosure_version', sa.String(length=20), nullable=False),
    sa.Column('created_by', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('material_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assigned_reviewer'], ['staff_user.id'], ),
    sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cases_clinic_id'), 'cases', ['clinic_id'], unique=False)
    op.create_table('briefing',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('body', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('proposed_by', sa.String(length=80), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_briefing_case_id'), 'briefing', ['case_id'], unique=False)
    op.create_index(op.f('ix_briefing_clinic_id'), 'briefing', ['clinic_id'], unique=False)
    op.create_table('case_link',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('opened', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_case_link_case_id'), 'case_link', ['case_id'], unique=False)
    op.create_index(op.f('ix_case_link_clinic_id'), 'case_link', ['clinic_id'], unique=False)
    op.create_table('deadline',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=60), nullable=False),
    sa.Column('date', sa.String(length=10), nullable=True),
    sa.Column('date_from_rule', sa.String(length=40), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('proposed_by', sa.String(length=80), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deadline_case_id'), 'deadline', ['case_id'], unique=False)
    op.create_index(op.f('ix_deadline_clinic_id'), 'deadline', ['clinic_id'], unique=False)
    op.create_table('derived',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('rule_config_version', sa.String(length=30), nullable=False),
    sa.Column('inputs_hash', sa.String(length=40), nullable=False),
    sa.Column('computed_by', sa.String(length=80), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_derived_case_id'), 'derived', ['case_id'], unique=False)
    op.create_index(op.f('ix_derived_clinic_id'), 'derived', ['clinic_id'], unique=False)
    op.create_table('document',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('document_type', sa.String(length=40), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('mime', sa.String(length=60), nullable=False),
    sa.Column('storage_path', sa.String(length=500), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('quality', sa.String(length=10), nullable=True),
    sa.Column('checks', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('exhibit', sa.String(length=4), nullable=True),
    sa.Column('uploaded_by', sa.String(length=80), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_case_id'), 'document', ['case_id'], unique=False)
    op.create_index(op.f('ix_document_clinic_id'), 'document', ['clinic_id'], unique=False)
    op.create_table('fact',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('field', sa.String(length=120), nullable=False),
    sa.Column('value', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('hedge', sa.Boolean(), nullable=False),
    sa.Column('confidence', sa.String(length=20), nullable=True),
    sa.Column('provenance', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('proposed_by', sa.String(length=80), nullable=False),
    sa.Column('supersedes', sa.String(length=40), nullable=True),
    sa.Column('superseded_by', sa.String(length=40), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('third_party', sa.Boolean(), nullable=False),
    sa.Column('matches_document', sa.String(length=40), nullable=True),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fact_case_id'), 'fact', ['case_id'], unique=False)
    op.create_index(op.f('ix_fact_clinic_id'), 'fact', ['clinic_id'], unique=False)
    op.create_index(op.f('ix_fact_field'), 'fact', ['field'], unique=False)
    op.create_table('flag',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('speed', sa.String(length=20), nullable=False),
    sa.Column('layer', sa.Integer(), nullable=False),
    sa.Column('field', sa.String(length=120), nullable=True),
    sa.Column('section', sa.String(length=80), nullable=True),
    sa.Column('rule_id', sa.String(length=40), nullable=True),
    sa.Column('detail', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('applicant_label_es', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('applicant_self_report', sa.Boolean(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_flag_case_id'), 'flag', ['case_id'], unique=False)
    op.create_index(op.f('ix_flag_clinic_id'), 'flag', ['clinic_id'], unique=False)
    op.create_table('gap',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('document_type', sa.String(length=40), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('label_es', sa.Text(), nullable=True),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('closed_by_document', sa.String(length=40), nullable=True),
    sa.Column('review_item_id', sa.String(length=40), nullable=True),
    sa.Column('proposed_by', sa.String(length=80), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_gap_case_id'), 'gap', ['case_id'], unique=False)
    op.create_index(op.f('ix_gap_clinic_id'), 'gap', ['clinic_id'], unique=False)
    op.create_table('memo',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('body_md', sa.Text(), nullable=False),
    sa.Column('proposed_by', sa.String(length=80), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_memo_case_id'), 'memo', ['case_id'], unique=False)
    op.create_index(op.f('ix_memo_clinic_id'), 'memo', ['clinic_id'], unique=False)
    op.create_table('packet',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=False),
    sa.Column('storage_path', sa.String(length=500), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('built_from_fact_versions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('signoff_id', sa.String(length=40), nullable=True),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_packet_case_id'), 'packet', ['case_id'], unique=False)
    op.create_index(op.f('ix_packet_clinic_id'), 'packet', ['clinic_id'], unique=False)
    op.create_table('review_item',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('flag_id', sa.String(length=40), nullable=True),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('speed', sa.String(length=20), nullable=False),
    sa.Column('field', sa.String(length=120), nullable=True),
    sa.Column('blocking', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('resolution_required', sa.String(length=40), nullable=True),
    sa.Column('trigger', sa.Text(), nullable=True),
    sa.Column('facts_summary', sa.Text(), nullable=True),
    sa.Column('agent_notes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('evidence', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('decision', sa.String(length=40), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('decided_by', sa.String(length=40), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('applicant_note_shown', sa.Boolean(), nullable=False),
    sa.Column('proposed_by', sa.String(length=80), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_review_item_case_id'), 'review_item', ['case_id'], unique=False)
    op.create_index(op.f('ix_review_item_clinic_id'), 'review_item', ['clinic_id'], unique=False)
    op.create_table('session',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('briefing_version', sa.Integer(), nullable=True),
    sa.Column('third_party_present', sa.Boolean(), nullable=False),
    sa.Column('third_party_relation', sa.String(length=40), nullable=True),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_session_case_id'), 'session', ['case_id'], unique=False)
    op.create_index(op.f('ix_session_clinic_id'), 'session', ['clinic_id'], unique=False)
    op.create_table('signoff',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('typed_name', sa.String(length=200), nullable=False),
    sa.Column('attestation_version', sa.String(length=20), nullable=False),
    sa.Column('section_confirmations', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('fact_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('facts_hash', sa.String(length=64), nullable=False),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('read_aloud', sa.Boolean(), nullable=False),
    sa.Column('assisted_by', sa.String(length=60), nullable=True),
    sa.Column('valid', sa.Boolean(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_signoff_case_id'), 'signoff', ['case_id'], unique=False)
    op.create_index(op.f('ix_signoff_clinic_id'), 'signoff', ['clinic_id'], unique=False)
    op.create_table('task',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('agent', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('title_es', sa.Text(), nullable=True),
    sa.Column('field', sa.String(length=120), nullable=True),
    sa.Column('question_es', sa.Text(), nullable=True),
    sa.Column('links', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('proposed_by', sa.String(length=80), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_case_id'), 'task', ['case_id'], unique=False)
    op.create_index(op.f('ix_task_clinic_id'), 'task', ['clinic_id'], unique=False)
    op.create_table('utterance',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('session_id', sa.String(length=40), nullable=True),
    sa.Column('speaker', sa.String(length=20), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('redacted', sa.Boolean(), nullable=False),
    sa.Column('locked', sa.Boolean(), nullable=False),
    sa.Column('meta', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_utterance_case_id'), 'utterance', ['case_id'], unique=False)
    op.create_index(op.f('ix_utterance_clinic_id'), 'utterance', ['clinic_id'], unique=False)
    op.create_table('extraction',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('clinic_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=40), nullable=False),
    sa.Column('document_id', sa.String(length=40), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('quality', sa.String(length=10), nullable=False),
    sa.Column('quality_reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('extractor', sa.String(length=40), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_extraction_case_id'), 'extraction', ['case_id'], unique=False)
    op.create_index(op.f('ix_extraction_clinic_id'), 'extraction', ['clinic_id'], unique=False)
    op.create_index(op.f('ix_extraction_document_id'), 'extraction', ['document_id'], unique=False)

    if op.get_bind().dialect.name == "postgresql":
        _postgres_extras()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("drop function if exists notify_event() cascade")
        op.execute("drop function if exists event_append_only() cascade")
    op.drop_index(op.f('ix_extraction_document_id'), table_name='extraction')
    op.drop_index(op.f('ix_extraction_clinic_id'), table_name='extraction')
    op.drop_index(op.f('ix_extraction_case_id'), table_name='extraction')
    op.drop_table('extraction')
    op.drop_index(op.f('ix_utterance_clinic_id'), table_name='utterance')
    op.drop_index(op.f('ix_utterance_case_id'), table_name='utterance')
    op.drop_table('utterance')
    op.drop_index(op.f('ix_task_clinic_id'), table_name='task')
    op.drop_index(op.f('ix_task_case_id'), table_name='task')
    op.drop_table('task')
    op.drop_index(op.f('ix_signoff_clinic_id'), table_name='signoff')
    op.drop_index(op.f('ix_signoff_case_id'), table_name='signoff')
    op.drop_table('signoff')
    op.drop_index(op.f('ix_session_clinic_id'), table_name='session')
    op.drop_index(op.f('ix_session_case_id'), table_name='session')
    op.drop_table('session')
    op.drop_index(op.f('ix_review_item_clinic_id'), table_name='review_item')
    op.drop_index(op.f('ix_review_item_case_id'), table_name='review_item')
    op.drop_table('review_item')
    op.drop_index(op.f('ix_packet_clinic_id'), table_name='packet')
    op.drop_index(op.f('ix_packet_case_id'), table_name='packet')
    op.drop_table('packet')
    op.drop_index(op.f('ix_memo_clinic_id'), table_name='memo')
    op.drop_index(op.f('ix_memo_case_id'), table_name='memo')
    op.drop_table('memo')
    op.drop_index(op.f('ix_gap_clinic_id'), table_name='gap')
    op.drop_index(op.f('ix_gap_case_id'), table_name='gap')
    op.drop_table('gap')
    op.drop_index(op.f('ix_flag_clinic_id'), table_name='flag')
    op.drop_index(op.f('ix_flag_case_id'), table_name='flag')
    op.drop_table('flag')
    op.drop_index(op.f('ix_fact_field'), table_name='fact')
    op.drop_index(op.f('ix_fact_clinic_id'), table_name='fact')
    op.drop_index(op.f('ix_fact_case_id'), table_name='fact')
    op.drop_table('fact')
    op.drop_index(op.f('ix_document_clinic_id'), table_name='document')
    op.drop_index(op.f('ix_document_case_id'), table_name='document')
    op.drop_table('document')
    op.drop_index(op.f('ix_derived_clinic_id'), table_name='derived')
    op.drop_index(op.f('ix_derived_case_id'), table_name='derived')
    op.drop_table('derived')
    op.drop_index(op.f('ix_deadline_clinic_id'), table_name='deadline')
    op.drop_index(op.f('ix_deadline_case_id'), table_name='deadline')
    op.drop_table('deadline')
    op.drop_index(op.f('ix_case_link_clinic_id'), table_name='case_link')
    op.drop_index(op.f('ix_case_link_case_id'), table_name='case_link')
    op.drop_table('case_link')
    op.drop_index(op.f('ix_briefing_clinic_id'), table_name='briefing')
    op.drop_index(op.f('ix_briefing_case_id'), table_name='briefing')
    op.drop_table('briefing')
    op.drop_index(op.f('ix_cases_clinic_id'), table_name='cases')
    op.drop_table('cases')
    op.drop_index(op.f('ix_staff_user_clinic_id'), table_name='staff_user')
    op.drop_table('staff_user')
    op.drop_index(op.f('ix_vault_value_clinic_id'), table_name='vault_value')
    op.drop_index(op.f('ix_vault_value_case_id'), table_name='vault_value')
    op.drop_table('vault_value')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_case_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_agent'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_event_kind'), table_name='event')
    op.drop_index(op.f('ix_event_clinic_id'), table_name='event')
    op.drop_index(op.f('ix_event_case_id'), table_name='event')
    op.drop_table('event')
    op.drop_table('clinic')
    op.drop_index(op.f('ix_agent_run_clinic_id'), table_name='agent_run')
    op.drop_index(op.f('ix_agent_run_case_id'), table_name='agent_run')
    op.drop_table('agent_run')

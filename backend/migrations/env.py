"""Alembic environment: the database comes from DATABASE_URL via ellis.config, the schema from ellis.db."""

from alembic import context

from ellis.db import Base, engine

with engine().connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()

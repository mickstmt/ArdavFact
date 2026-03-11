"""add tipo_cambio table

Revision ID: a3f8c1e92d07
Revises: d15766f064bc
Create Date: 2026-03-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f8c1e92d07'
down_revision = 'd15766f064bc'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tipo_cambio',
        sa.Column('id',    sa.Integer(),        nullable=False),
        sa.Column('fecha', sa.Date(),            nullable=False),
        sa.Column('valor', sa.Numeric(10, 4),    nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fecha'),
    )
    op.create_index('ix_tipo_cambio_fecha', 'tipo_cambio', ['fecha'], unique=True)


def downgrade():
    op.drop_index('ix_tipo_cambio_fecha', table_name='tipo_cambio')
    op.drop_table('tipo_cambio')

"""initial_migration

Revision ID: 62b8df961103
Revises: 
Create Date: 2025-05-17 13:43:41.088299

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '62b8df961103'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=True),
    sa.Column('telegram_token', sa.String(length=256), nullable=True),
    sa.Column('telegram_chat_id', sa.String(length=64), nullable=True),
    sa.Column('teams_webhook', sa.String(length=512), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('notification_preference', sa.String(length=20), nullable=True),
    sa.Column('summary_times', sa.String(length=100), nullable=True),
    sa.Column('notify_only_changes', sa.Boolean(), nullable=True),
    sa.Column('gemini_api_key', sa.String(length=256), nullable=True),
    sa.Column('gemini_model_preference', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('website',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=True),
    sa.Column('frequency_type', sa.String(length=32), nullable=True),
    sa.Column('frequency_value', sa.String(length=128), nullable=True),
    sa.Column('last_checked', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('error_message', sa.String(length=512), nullable=True),
    sa.Column('ai_focus_area', sa.String(length=256), nullable=True),
    sa.Column('proxy', sa.String(length=128), nullable=True),
    sa.Column('monitoring_type', sa.String(length=50), nullable=True),
    sa.Column('monitoring_keywords', sa.Text(), nullable=True),
    sa.Column('visual_focus_zones', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.user_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('check_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('website_id', sa.Integer(), nullable=True),
    sa.Column('checked_at', sa.DateTime(), nullable=True),
    sa.Column('screenshot_path', sa.String(length=256), nullable=True),
    sa.Column('html_path', sa.String(length=256), nullable=True),
    sa.Column('diff_path', sa.String(length=256), nullable=True),
    sa.Column('ai_description', sa.Text(), nullable=True),
    sa.Column('change_detected', sa.Boolean(), nullable=True),
    sa.Column('error', sa.String(length=512), nullable=True),
    sa.Column('response_time', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['website_id'], ['website.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('notification',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=True),
    sa.Column('website_id', sa.Integer(), nullable=True),
    sa.Column('check_history_id', sa.Integer(), nullable=True),
    sa.Column('notification_type', sa.String(length=20), nullable=True),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('screenshot_path', sa.String(length=256), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('sent', sa.Boolean(), nullable=True),
    sa.Column('included_in_summary', sa.Boolean(), nullable=True),
    sa.Column('summary_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['check_history_id'], ['check_history.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.user_id'], ),
    sa.ForeignKeyConstraint(['website_id'], ['website.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('notification')
    op.drop_table('check_history')
    op.drop_table('website')
    op.drop_table('user')
    # ### end Alembic commands ###

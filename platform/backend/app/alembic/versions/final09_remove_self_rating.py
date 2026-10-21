"""移除学生自评列及历史报告、事件中的结构化自评数据。

Revision ID: final09
Revises: final08
"""
from alembic import op

revision = "final09"
down_revision = "final08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 临时函数递归处理对象和数组，包含旧版反馈 knowledge_points[].self_rating。
    op.execute("""
        CREATE OR REPLACE FUNCTION pg_temp.remove_student_self_assessment(value jsonb)
        RETURNS jsonb LANGUAGE plpgsql AS $$
        DECLARE result jsonb;
        BEGIN
            IF jsonb_typeof(value) = 'object' THEN
                SELECT COALESCE(jsonb_object_agg(key, pg_temp.remove_student_self_assessment(val)), '{}'::jsonb)
                INTO result FROM jsonb_each(value) AS item(key, val)
                WHERE key NOT IN ('self_rating', 'self_ratings', 'tutoring_self_ratings', '_persisted_self_ratings');
                RETURN result;
            ELSIF jsonb_typeof(value) = 'array' THEN
                SELECT COALESCE(jsonb_agg(pg_temp.remove_student_self_assessment(val) ORDER BY position), '[]'::jsonb)
                INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS item(val, position);
                RETURN result;
            END IF;
            RETURN value;
        END;
        $$
    """)
    for table in ("after_class_reports", "learning_events"):
        op.execute(f"UPDATE student.{table} "
                   "SET payload = pg_temp.remove_student_self_assessment(payload) "
                   "WHERE payload::text ~ '\"(self_rating|self_ratings|tutoring_self_ratings|_persisted_self_ratings)\"[[:space:]]*:'")
    op.execute("DROP FUNCTION pg_temp.remove_student_self_assessment(jsonb)")
    op.execute("ALTER TABLE student.knowledge_mastery DROP COLUMN IF EXISTS self_rating")


def downgrade() -> None:
    # 仅恢复旧列结构，已删除的自评数据不恢复。
    op.execute("ALTER TABLE student.knowledge_mastery ADD COLUMN IF NOT EXISTS self_rating INTEGER")

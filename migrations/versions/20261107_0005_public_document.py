"""公開用の文書（Viewer が読む内容）を表に持つ（Anime の移行 0003 をそのまま移植）

Revision ID: 0005

画面の内容（変化の一覧・作品ごと）は、書く側（publication/publishing）が分析の表から作り、
検査に通ったものだけを public_document に 1 つの取引で置き換える。処理の層のアプリ（FastAPI）は鍵（path）で 1 行を読んで返すだけ。
public_build は、作った回ごとの記録（材料の版・結果・理由）。最後に公開した回の材料の版と比べて、変わったときだけ作り直す。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_build",
        sa.Column("build_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("input_version", sa.Text, nullable=False),     # 材料の版（分析の規則の版・最後の分析の時刻・取得元の最新の報告）
        sa.Column("trigger", sa.Text, nullable=False),           # daily / manual
        sa.Column("status", sa.Text, nullable=False),            # running / published / rejected（検査に通らない）/ failed（作れない）
        sa.Column("latest_day", sa.Date),                        # 公開した内容の最新の日
        sa.Column("documents", sa.Integer),
        sa.Column("detail", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),   # 所要時間・検査の理由（公開しない）
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('running', 'published', 'rejected', 'failed')", name="public_build_status"),
    )
    op.create_index("public_build_finished", "public_build", ["finished_at"])
    # 本文は json（受け取った文字のまま持つ。中を問い合わせないので jsonb にしない。返すときに作り直さない）
    op.create_table(
        "public_document",
        sa.Column("path", sa.Text, primary_key=True),            # overview / game/<appid>
        sa.Column("body", postgresql.JSON, nullable=False),
        sa.Column("build_id", sa.BigInteger, sa.ForeignKey("public_build.build_id"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("public_document")
    op.drop_index("public_build_finished", table_name="public_build")
    op.drop_table("public_build")

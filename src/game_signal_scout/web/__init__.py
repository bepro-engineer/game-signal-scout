"""画面の処理の層（標準の三層。ADR 0056・0057）。公開用の文書の表（public_document）を読んで返すだけで、内容は作らない（作るのは publication/）。

- app.py: アプリ（FastAPI）の組み立て。接続の溜め・誤りの扱い
- routers/: Controller（接続口 /api/… と、ページの骨組み）
- services/public_content.py: 公開用の文書を読む Service（Repository repositories/public_document を呼ぶ）
- pages.py・templates/: View（ページの骨組みの HTML。Jinja2）。static/: 画面の部品（JavaScript・CSS・画像）
- 決定: docs/adr/0056-standard-three-tier.md・0057-public-document-read-model.md
"""

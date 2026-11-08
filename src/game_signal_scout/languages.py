"""言語の値の扱い（全 Source・全画面で 1 つ）。投稿の言語の判定の結果のうち、言語圏として数えない値。
集計の「すべての言語の合計」の行（observations.TOTAL = "*"）は言語でない値とは別の意味なので、使う側で別に扱う。"""
from __future__ import annotations

NOT_LANGUAGE = frozenset({"und", "zxx", "mul", "uncertain", None, ""})   # 判定できない・言語の内容がない・複数・不確か・空


def is_language(code) -> bool:
    return code not in NOT_LANGUAGE


# 言語の名前（日本語・英語。画面・公開の文章・今日の兆しの検査が使う 1 つの表。#46 D7: 3 か所に分かれていた）
NAMES = {"ja": ("日本語", "Japanese"), "en": ("英語", "English"), "es": ("スペイン語", "Spanish"), "pt": ("ポルトガル語", "Portuguese"),
         "fr": ("フランス語", "French"), "de": ("ドイツ語", "German"), "ko": ("韓国語", "Korean"), "zh": ("中国語", "Chinese"),
         "th": ("タイ語", "Thai"), "ar": ("アラビア語", "Arabic"), "id": ("インドネシア語", "Indonesian"), "it": ("イタリア語", "Italian"),
         "ru": ("ロシア語", "Russian"), "tr": ("トルコ語", "Turkish"), "ca": ("カタルーニャ語", "Catalan"), "fi": ("フィンランド語", "Finnish"),
         "el": ("ギリシャ語", "Greek"), "cs": ("チェコ語", "Czech"), "uk": ("ウクライナ語", "Ukrainian"), "pcm": ("ナイジェリア・ピジン語", "Nigerian Pidgin"),
         "nl": ("オランダ語", "Dutch"), "pl": ("ポーランド語", "Polish"), "sv": ("スウェーデン語", "Swedish"), "hu": ("ハンガリー語", "Hungarian"),
         "vi": ("ベトナム語", "Vietnamese"), "tl": ("タガログ語", "Tagalog"), "und": ("判定できない", "Unknown")}

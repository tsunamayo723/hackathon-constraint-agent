"""
Geminiエージェント群

役割（パーサ / ハンドラ生成 / テスト生成 …）ごとに1エージェント。
各エージェントは「どのモデルを使うか」「どんな構造化出力か」「どのプロンプトか」を
宣言するだけ。呼ぶ側はモデルやプロンプトの中身を知らなくてよい。

  ParserAgent  : 自然言語 → 制約JSON（Flash・高頻度）
  （今後）HandlerAgent : 未知typeのハンドラ生成（Pro・高精度）
"""

from .parser_agent import ParserAgent, parse
from .handler_agent import GeneratedHandler, HandlerAgent
from .note_agent import NoteAgent, NoteResult

__all__ = ["ParserAgent", "parse", "HandlerAgent", "GeneratedHandler", "NoteAgent", "NoteResult"]

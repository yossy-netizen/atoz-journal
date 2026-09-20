"""PitchTrace: 生楽器のピッチ挙動をトレースして MIDI に適用する。

構成:
- profile   … 楽器 × スタイルごとのパラメータ分布（JSON）
- notes     … 音符列の表現と MIDI 読み込み・フレーズ分割
- generate  … 音符列 + プロファイル → セント偏差カーブ c(t)
- render_midi … c(t) → ピッチベンド / MPE / CC 付き MIDI
- f0 / analyze … 音声 → F0 → ノート分割 → 成分推定 → プロファイル
- synth     … A/B 試聴用の簡易シンセ
"""

from .profile import Profile, load_profile, list_builtin_profiles
from .notes import Note, load_midi_notes, split_phrases
from .generate import generate_contour, Contour

__all__ = [
    "Profile",
    "load_profile",
    "list_builtin_profiles",
    "Note",
    "load_midi_notes",
    "split_phrases",
    "generate_contour",
    "Contour",
]

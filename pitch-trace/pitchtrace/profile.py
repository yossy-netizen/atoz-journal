"""プロファイル: 楽器 × スタイルごとのピッチ挙動パラメータ分布。

各パラメータは ``Dist``（mean / std / min / max）で表し、音符ごとに
クランプ付き正規分布からサンプリングする。JSON の構造は
``pitchtrace/profiles/*.json`` を参照。解析（analyze）が出力する JSON も
同じ構造なので、そのまま render に渡せる。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class Dist:
    """クランプ付き正規分布。"""

    mean: float
    std: float = 0.0
    min: float | None = None
    max: float | None = None

    def sample(self, rng: np.random.Generator, scale: float = 1.0) -> float:
        v = self.mean + rng.normal() * self.std * scale
        if self.min is not None:
            v = max(v, self.min)
        if self.max is not None:
            v = min(v, self.max)
        return float(v)

    @classmethod
    def from_any(cls, v: Any) -> "Dist":
        if isinstance(v, Dist):
            return v
        if isinstance(v, (int, float)):
            return cls(mean=float(v))
        if isinstance(v, dict):
            return cls(
                mean=float(v.get("mean", 0.0)),
                std=float(v.get("std", 0.0)),
                min=None if v.get("min") is None else float(v["min"]),
                max=None if v.get("max") is None else float(v["max"]),
            )
        raise TypeError(f"Dist に変換できません: {v!r}")

    def to_dict(self) -> dict:
        d = {"mean": round(self.mean, 4), "std": round(self.std, 4)}
        if self.min is not None:
            d["min"] = round(self.min, 4)
        if self.max is not None:
            d["max"] = round(self.max, 4)
        return d


@dataclass
class Intonation:
    cents: Dist = field(default_factory=lambda: Dist(0.0, 5.0, -25.0, 25.0))
    # 音符間の相関（0 = 毎回独立、1 = 前の音と同じ偏差を引き継ぐ）
    continuity: float = 0.5


@dataclass
class Transition:
    # レガート（前の音との隙間が max_gap_ms 以下）のときにポルタメントを付ける確率
    prob: float = 0.7
    max_gap_ms: float = 40.0
    # ポルタメントの所要時間。進行率 20%→80% にかかる時間で定義する（解析で直接測れる量）。
    # 実際の滑り全体は sharpness に応じてこの 2〜3 倍になる
    duration_ms: Dist = field(default_factory=lambda: Dist(30.0, 10.0, 8.0, 150.0))
    duration_per_semitone_ms: float = 4.0
    # シグモイドの鋭さ（大きいほど中央で一気に動く）
    sharpness: Dist = field(default_factory=lambda: Dist(6.0, 1.5, 3.0, 12.0))
    # 目標音を行き過ぎる量（セント、進行方向）
    overshoot_cents: Dist = field(default_factory=lambda: Dist(4.0, 4.0, 0.0, 25.0))
    overshoot_settle_ms: float = 60.0


@dataclass
class Attack:
    # 非レガートの発音時にしゃくり／オーバーシュートを付ける確率
    prob: float = 0.6
    offset_cents: Dist = field(default_factory=lambda: Dist(-10.0, 10.0, -60.0, 30.0))
    settle_ms: Dist = field(default_factory=lambda: Dist(40.0, 15.0, 10.0, 150.0))


@dataclass
class Vibrato:
    prob: float = 0.9
    min_note_ms: float = 250.0
    rate_hz: Dist = field(default_factory=lambda: Dist(5.8, 0.5, 4.0, 8.0))
    # 振幅（片側、セント）。peak-to-peak はこの 2 倍
    depth_cents: Dist = field(default_factory=lambda: Dist(25.0, 8.0, 5.0, 60.0))
    onset_ms: Dist = field(default_factory=lambda: Dist(150.0, 60.0, 0.0, 500.0))
    ramp_ms: Dist = field(default_factory=lambda: Dist(200.0, 80.0, 30.0, 600.0))
    # 中心のずれ（depth に対する比。-1 = 目標音より完全に下側で揺れる）
    center_offset: float = -0.3
    # レート・深さのゆっくりした揺らぎ（比）
    rate_wobble: float = 0.06
    depth_wobble: float = 0.15
    # 波形の非対称（0 = 正弦波、+ で上向きが鋭い）
    asymmetry: float = 0.0
    # フレーズの山（最高音）での深さの倍率
    climax_gain: float = 1.3
    # 音長が長いほど深くなる（この長さ ms で最大）
    full_depth_at_ms: float = 1000.0


@dataclass
class Drift:
    cents: Dist = field(default_factory=lambda: Dist(4.0, 2.0, 0.0, 15.0))
    cutoff_hz: float = 1.0


@dataclass
class Release:
    prob: float = 0.5
    cents: Dist = field(default_factory=lambda: Dist(-8.0, 6.0, -60.0, 10.0))
    duration_ms: Dist = field(default_factory=lambda: Dist(60.0, 25.0, 15.0, 250.0))
    phrase_end_gain: float = 2.0


@dataclass
class Jitter:
    cents: float = 1.0
    smooth_ms: float = 15.0


@dataclass
class Dynamics:
    """音量表情（CC11 等）。値は 0..1 の相対レベルで、レンダリング時に CC 値へ変換する。"""

    enabled: bool = True
    cc_number: int = 11
    # ベロシティ 100 のときの基準レベル（0..1）と、ベロシティの効き（0 = 無視、1 = 比例）
    base: float = 0.75
    velocity_weight: float = 0.5
    # 発音時のふくらみ: attack_from × レベルから attack_ms かけて本来のレベルへ
    attack_ms: Dist = field(default_factory=lambda: Dist(60.0, 25.0, 10.0, 250.0))
    attack_from: Dist = field(default_factory=lambda: Dist(0.55, 0.15, 0.2, 1.0))
    # サステイン中の傾き（1 秒あたりの比率。負でデクレッシェンド）
    sustain_slope: Dist = field(default_factory=lambda: Dist(-0.05, 0.08, -0.4, 0.3))
    # 音末の減衰（次の音がレガートでないときだけ）
    release_ms: Dist = field(default_factory=lambda: Dist(80.0, 30.0, 20.0, 300.0))
    release_to: Dist = field(default_factory=lambda: Dist(0.4, 0.15, 0.05, 1.0))
    # フレーズの山に向かうクレッシェンド量（±この半分）
    phrase_arc: float = 0.2
    # ゆっくりした揺らぎ（比）
    wobble: float = 0.03
    min: float = 0.05
    max: float = 1.0


@dataclass
class Timing:
    """マイクロタイミング（オフライン専用。リアルタイムでは未来を動かせない）。"""

    enabled: bool = True
    onset_ms: Dist = field(default_factory=lambda: Dist(0.0, 8.0, -30.0, 30.0))
    # レガートの音は少し早めに入る / フレーズ先頭は少し遅れる
    legato_lead_ms: Dist = field(default_factory=lambda: Dist(6.0, 4.0, 0.0, 25.0))
    phrase_first_delay_ms: Dist = field(default_factory=lambda: Dist(8.0, 6.0, 0.0, 40.0))
    # 非レガートの音は次の音との間に隙間を作る（音を短くする）
    detach_gap_ms: Dist = field(default_factory=lambda: Dist(25.0, 12.0, 0.0, 100.0))


@dataclass
class Output:
    # ビブラート成分をどのレーンに出すか: "bend" | "cc"
    vibrato_lane: str = "bend"
    cc_number: int = 1
    # cc レーン時、depth_cents がこの値のとき CC=127
    cc_full_depth_cents: float = 50.0


@dataclass
class Profile:
    name: str = "custom"
    instrument: str = "unknown"
    style: str = "unknown"
    version: int = 0
    source: str = ""
    hop_ms: float = 5.0
    intonation: Intonation = field(default_factory=Intonation)
    transition: Transition = field(default_factory=Transition)
    attack: Attack = field(default_factory=Attack)
    vibrato: Vibrato = field(default_factory=Vibrato)
    drift: Drift = field(default_factory=Drift)
    release: Release = field(default_factory=Release)
    jitter: Jitter = field(default_factory=Jitter)
    dynamics: Dynamics = field(default_factory=Dynamics)
    timing: Timing = field(default_factory=Timing)
    output: Output = field(default_factory=Output)
    # 解析由来の場合の統計（音符数など）。生成には使わない
    stats: dict = field(default_factory=dict)

    # ---- (de)serialisation -------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        p = cls()
        for key in ("name", "instrument", "style", "version", "source", "hop_ms", "stats"):
            if key in d:
                setattr(p, key, d[key])
        for section in ("intonation", "transition", "attack", "vibrato", "drift", "release", "jitter", "dynamics", "timing", "output"):
            if section not in d:
                continue
            obj = getattr(p, section)
            for k, v in d[section].items():
                if not hasattr(obj, k):
                    raise KeyError(f"プロファイル {section}.{k} は未知のパラメータです")
                cur = getattr(obj, k)
                if isinstance(cur, Dist):
                    setattr(obj, k, Dist.from_any(v))
                else:
                    setattr(obj, k, type(cur)(v) if cur is not None else v)
        return p

    def to_dict(self) -> dict:
        def conv(o):
            if isinstance(o, Dist):
                return o.to_dict()
            if hasattr(o, "__dataclass_fields__"):
                return {k: conv(getattr(o, k)) for k in o.__dataclass_fields__}
            return o

        return conv(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def list_builtin_profiles() -> list[str]:
    names = []
    for entry in resources.files("pitchtrace.profiles").iterdir():
        if entry.name.endswith(".json"):
            names.append(entry.name[:-5])
    return sorted(names)


def load_profile(name_or_path: str | Path) -> Profile:
    """組み込み名（例 ``violin_classical``）または JSON ファイルパスから読み込む。"""
    p = Path(name_or_path)
    if p.suffix == ".json" and p.exists():
        return Profile.from_dict(json.loads(p.read_text(encoding="utf-8")))
    entry = resources.files("pitchtrace.profiles") / f"{name_or_path}.json"
    if entry.is_file():
        return Profile.from_dict(json.loads(entry.read_text(encoding="utf-8")))
    raise FileNotFoundError(
        f"プロファイル '{name_or_path}' が見つかりません。組み込み: {', '.join(list_builtin_profiles())}"
    )

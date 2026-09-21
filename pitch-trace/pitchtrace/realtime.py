"""リアルタイム MIDI 処理: DAW からのノートを受け、ピッチベンド付きで返す。

``RealtimeTracer`` は MIDI ポートに依存しない純粋なエンジンで、``handle(msg, now)`` で入力を、
``tick(now)`` で時間の進行を受け取り、``send`` コールバックに出力を渡す。
実ポートへの接続は ``run_live``（python-rtmidi 経由の mido）が行う。

リアルタイムでは「次の音」と「音長」が分からないため:
- ポルタメントは新しい音のノートオン時に、前の音のピッチから滑る（前の音は既知）
- ビブラート深さの音長依存は「十分に長い音」を仮定する
- フレーズ末のリリースとクライマックスの強調は付けない
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import mido
import numpy as np

from .generate import NoteContext, NoteContour, generate_note
from .key import detect_key
from .notes import Note
from .profile import Profile
from .render_midi import cents_to_bend, _mpe_config, _rpn_bend_range


@dataclass
class _Active:
    contour: NoteContour
    pitch: int
    onset: float
    channel: int
    next_k: int = 0          # 次に出すサンプル番号
    last_bend: int | None = None
    last_cc: int | None = None
    last_dyn: int | None = None


@dataclass
class RealtimeTracer:
    profile: Profile
    send: Callable[[mido.Message], None]
    mode: str = "single"            # "single" | "mpe"
    bend_range: int = 12
    channel: int = 0                # single モードの出力チャンネル
    seed: int | None = None
    amount: float = 1.0
    max_note_s: float = 30.0        # 1 音あたり生成しておく最大長
    legato_overlap_s: float = 0.0   # single モードで前の音を残す時間
    passthrough: bool = True        # ノート以外のメッセージをそのまま通す
    dynamics: bool = True           # ダイナミクス CC を出す
    key: tuple[int, str] | None = None  # 調（度数バイアス用）。key_auto=True なら直近の音符から推定して更新
    key_auto: bool = False
    key_window: int = 16                # 自動判定に使う直近の音符数
    _recent: list = field(init=False, default_factory=list)

    rng: np.random.Generator = field(init=False)
    active: dict[int, _Active] = field(init=False, default_factory=dict)  # pitch → 状態
    _pending_off: list[tuple[float, int, int]] = field(init=False, default_factory=list)  # (time, pitch, ch)
    _prev: NoteContext = field(init=False, default_factory=NoteContext)
    _prev_off_time: float = field(init=False, default=-1e9)
    _last_onset: float = field(init=False, default=-1e9)
    _free_channels: list[int] = field(init=False, default_factory=list)
    stats: dict = field(init=False, default_factory=lambda: {"notes": 0, "portamento": 0, "vibrato": 0, "bend_events": 0})

    def __post_init__(self):
        if self.mode not in ("single", "mpe"):
            raise ValueError("mode は 'single' か 'mpe'")
        self.rng = np.random.default_rng(self.seed)
        self.hop_s = self.profile.hop_ms / 1000.0
        self._free_channels = list(range(1, 16))

    # ---- 初期化メッセージ --------------------------------------------------
    def setup_messages(self) -> list[mido.Message]:
        if self.mode == "single":
            return _rpn_bend_range(self.channel, self.bend_range)
        msgs = _mpe_config(0, 15)
        for ch in range(1, 16):
            msgs += _rpn_bend_range(ch, self.bend_range)
        return msgs

    def start(self) -> None:
        for m in self.setup_messages():
            self.send(m)

    # ---- 入力 --------------------------------------------------------------
    def handle(self, msg: mido.Message, now: float) -> None:
        if msg.type == "note_on" and msg.velocity > 0:
            self._note_on(msg.note, msg.velocity, now)
        elif msg.type in ("note_off", "note_on"):
            self._note_off(msg.note, now)
        elif msg.type == "control_change" and msg.control in (120, 123):
            self.all_notes_off(now)
        elif self.passthrough and hasattr(msg, "channel"):
            out_ch = self.channel if self.mode == "single" else 0
            self.send(msg.copy(channel=out_ch))
        elif self.passthrough:
            self.send(msg)

    def _alloc_channel(self, now: float) -> int:
        if self.mode == "single":
            return self.channel
        if not self._free_channels:
            # 全チャンネル使用中: 最も古い音を切る
            oldest = min(self.active.values(), key=lambda a: a.onset)
            self._note_off(oldest.pitch, now)
        return self._free_channels.pop(0)

    def _note_on(self, pitch: int, velocity: int, now: float) -> None:
        if pitch in self.active:
            self._note_off(pitch, now)
        # 同じ音の note_off が保留中なら先に出す（後から届くと新しい音を消してしまう）
        for item in [x for x in self._pending_off if x[1] == pitch]:
            self._pending_off.remove(item)
            self.send(mido.Message("note_off", channel=item[2], note=pitch, velocity=0))
            self._release_channel(item[2])
        # 前の音との関係。まだ鳴っている音があれば重なり（gap < 0）= レガート
        if self.active:
            gap = -1.0
        else:
            gap = now - self._prev_off_time
        if self.mode == "single" and self.active:
            for p in list(self.active):
                if self.legato_overlap_s > 0:
                    a = self.active.pop(p)
                    self._pending_off.append((now + self.legato_overlap_s, p, a.channel))
                    self._remember_prev(a, now)
                else:
                    self._note_off(p, now)
        if self.active:
            # まだ鳴っている音がある（MPE の重なり）: 直近に始まった音の現在位置から滑る
            newest = max(self.active.values(), key=lambda a: a.onset)
            ctx = self._context_from(newest, now, gap)
        else:
            ctx = NoteContext(prev_pitch=self._prev.prev_pitch, gap_s=gap, prev_end_cents=self._prev.prev_end_cents,
                              prev_intonation=self._prev.prev_intonation, next_legato=None, phrase_end=None, is_climax=False,
                              key=self.key)
        note = Note(pitch=pitch, onset=now, duration=self.max_note_s, velocity=velocity)
        contour = generate_note(note, ctx, self.profile, self.rng, amount=self.amount, duration_s=self.max_note_s)
        ch = self._alloc_channel(now)
        a = _Active(contour=contour, pitch=pitch, onset=now, channel=ch)
        self.active[pitch] = a
        self._emit_sample(a, 0)   # ノートオンより先にベンドを出す
        a.next_k = 1
        self.send(mido.Message("note_on", channel=ch, note=pitch, velocity=velocity))
        self._last_onset = now
        self.stats["notes"] += 1
        self.stats["portamento"] += int(bool(contour.params.get("portamento")))
        self.stats["vibrato"] += int("vibrato_rate_hz" in contour.params)

    def _context_from(self, a: _Active, now: float, gap: float = 1e9) -> NoteContext:
        """鳴っている（または今切った）音 a の now 時点の状態から、次の音の NoteContext を作る。"""
        k = int((now - a.onset) / self.hop_s)
        return NoteContext(prev_pitch=a.pitch, gap_s=gap, prev_end_cents=a.contour.end_cents_at(k),
                           prev_intonation=a.contour.params["intonation_random"],
                           next_legato=None, phrase_end=None, is_climax=False, key=self.key)

    def _remember_prev(self, a: _Active, now: float) -> None:
        self._prev = self._context_from(a, now)
        self._prev_off_time = now
        if self.key_auto:
            self._recent.append(Note(pitch=a.pitch, onset=a.onset, duration=max(now - a.onset, 0.05)))
            self._recent = self._recent[-self.key_window:]
            if len(self._recent) >= 6:
                pc, mode, r = detect_key(self._recent)
                if r > 0.5:
                    self.key = (pc, mode)

    def _note_off(self, pitch: int, now: float) -> None:
        a = self.active.pop(pitch, None)
        if a is None:
            return
        self.send(mido.Message("note_off", channel=a.channel, note=pitch, velocity=0))
        self._remember_prev(a, now)
        self._release_channel(a.channel)

    def _release_channel(self, ch: int) -> None:
        if self.mode == "mpe":
            self.send(mido.Message("pitchwheel", channel=ch, pitch=0))
            self._free_channels.append(ch)
        elif not self.active and not self._pending_off:
            self.send(mido.Message("pitchwheel", channel=ch, pitch=0))

    def all_notes_off(self, now: float) -> None:
        for p in list(self.active):
            self._note_off(p, now)
        # 先に保留リストを空にしないと、single モードの _release_channel がベンドを戻さない
        pending, self._pending_off = self._pending_off, []
        for _, p, ch in pending:
            self.send(mido.Message("note_off", channel=ch, note=p, velocity=0))
            self._release_channel(ch)

    # ---- 時間の進行 --------------------------------------------------------
    def _emit_sample(self, a: _Active, k: int) -> None:
        nc = a.contour
        if k >= len(nc.t):
            return
        use_cc = self.profile.output.vibrato_lane == "cc"
        cents = nc.cents[k] - (nc.parts["vibrato"][k] if use_cc else 0.0)
        val = int(cents_to_bend(np.array([cents]), self.bend_range)[0])
        if val != a.last_bend:
            self.send(mido.Message("pitchwheel", channel=a.channel, pitch=val))
            a.last_bend = val
            self.stats["bend_events"] += 1
        if use_cc:
            cc = int(np.clip(round(nc.vib_env[k] / max(self.profile.output.cc_full_depth_cents, 1e-6) * 127), 0, 127))
            if cc != a.last_cc:
                self.send(mido.Message("control_change", channel=a.channel, control=self.profile.output.cc_number, value=cc))
                a.last_cc = cc
        if self.dynamics and self.profile.dynamics.enabled and nc.dyn is not None:
            dv = int(np.clip(round(nc.dyn[k] * 127), 0, 127))
            if dv != a.last_dyn:
                self.send(mido.Message("control_change", channel=a.channel, control=self.profile.dynamics.cc_number, value=dv))
                a.last_dyn = dv

    def tick(self, now: float) -> None:
        """now までに出すべきベンド / CC を出す。"""
        for a in list(self.active.values()):
            k_due = int((now - a.onset) / self.hop_s)
            while a.next_k <= k_due and a.next_k < len(a.contour.t):
                self._emit_sample(a, a.next_k)
                a.next_k += 1
        if self._pending_off:
            due = [x for x in self._pending_off if x[0] <= now]
            if due:
                self._pending_off = [x for x in self._pending_off if x[0] > now]
                for _, p, ch in due:
                    self.send(mido.Message("note_off", channel=ch, note=p, velocity=0))
                    self._release_channel(ch)


# ----------------------------------------------------------------------------
# 実ポート
# ----------------------------------------------------------------------------

def list_ports() -> tuple[list[str], list[str]]:
    return mido.get_input_names(), mido.get_output_names()


def _open_ports(in_name: str | None, out_name: str | None):
    """ポートを開く。名前は部分一致。'virtual' なら仮想ポートを作る（macOS / Linux）。"""
    def pick(names, want):
        for n in names:
            if want.lower() in n.lower():
                return n
        raise SystemExit(f"ポート '{want}' が見つかりません。候補: {names}")

    if in_name in (None, "virtual"):
        inport = mido.open_input("PitchTrace In", virtual=True)
    else:
        inport = mido.open_input(pick(mido.get_input_names(), in_name))
    if out_name in (None, "virtual"):
        outport = mido.open_output("PitchTrace Out", virtual=True)
    else:
        outport = mido.open_output(pick(mido.get_output_names(), out_name))
    return inport, outport


def run_live(tracer_factory: Callable[[Callable[[mido.Message], None]], RealtimeTracer],
             in_name: str | None, out_name: str | None, in_channel: int | None = None,
             poll_s: float = 0.001, verbose: bool = False) -> None:
    inport, outport = _open_ports(in_name, out_name)
    tracer = tracer_factory(outport.send)
    tracer.start()
    print(f"PitchTrace live: {inport.name} → {outport.name}  (profile={tracer.profile.name}, mode={tracer.mode}, bend={tracer.bend_range})")
    print("Ctrl+C で終了")
    t0 = time.monotonic()
    try:
        while True:
            now = time.monotonic() - t0
            for msg in inport.iter_pending():
                if in_channel is not None and getattr(msg, "channel", in_channel) != in_channel:
                    continue
                if verbose:
                    print(f"{now:8.3f} in  {msg}")
                tracer.handle(msg, now)
            tracer.tick(now)
            time.sleep(poll_s)
    except KeyboardInterrupt:
        pass
    finally:
        tracer.all_notes_off(time.monotonic() - t0)
        print(f"stats: {tracer.stats}")
        inport.close()
        outport.close()

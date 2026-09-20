"""コマンドライン:

  pitchtrace profiles                       組み込みプロファイル一覧
  pitchtrace info    in.mid                 トラック一覧（--track の番号を調べる）
  pitchtrace render  in.mid out.mid [opts]  MIDI に表情（ピッチベンド等）を付ける
  pitchtrace analyze in.wav -o prof.json    ソロ録音からプロファイルを作る
  pitchtrace demo    out_dir [opts]         静止ピッチ / トレース済みの A/B 用 WAV と MIDI を作る
  pitchtrace dump    in.mid out.csv [opts]  生成したカーブを CSV で書き出す（可視化用）
  pitchtrace ports                          MIDI ポート一覧
  pitchtrace live    [--in NAME] [--out NAME] [opts]
                                            DAW からリアルタイムに受けてピッチベンド付きで返す
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import mido
import numpy as np

from .analyze import analyze_audio, build_profile
from .generate import generate_contour
from .key import key_name, parse_key
from .notes import Note, TempoMap, describe_midi, load_midi_notes, make_monophonic
from .profile import list_builtin_profiles, load_profile
from .render_midi import render_midi
from .synth import read_wav, synthesize, write_wav


def _add_render_opts(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--profile", "-p", default="violin_classical", help="組み込み名または JSON パス")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--amount", type=float, default=1.0, help="全体量（0 = 静止ピッチ）")
    ap.add_argument("--mode", choices=["single", "mpe"], default="single")
    ap.add_argument("--bend-range", type=int, default=12, help="ベンドレンジ（半音）。音源側と揃える")
    ap.add_argument("--legato-overlap-ms", type=float, default=0.0, help="single モードで残す重なり")
    ap.add_argument("--no-lookahead", action="store_true", help="次の音を見ない（リアルタイム動作の模擬）")
    ap.add_argument("--max-events-per-s", type=float, default=None, help="ベンド/CC の最大密度")
    ap.add_argument("--vibrato-lane", choices=["bend", "cc"], default=None, help="ビブラートの出力先を上書き")
    ap.add_argument("--key", default=None, help="調を指定（例 C, F#, Bb, Am）。省略時は render では自動判定、live では度数バイアスなし")
    ap.add_argument("--no-key-bias", action="store_true", help="調に対する度数バイアスを付けない")
    ap.add_argument("--no-dynamics", action="store_true", help="ダイナミクス CC を出さない")
    ap.add_argument("--no-timing", action="store_true", help="マイクロタイミングを適用しない")
    ap.add_argument("--dyn-cc", type=int, default=None, help="ダイナミクスの CC 番号を上書き（既定 11）")
    ap.add_argument("--tempo", type=float, default=None, help="出力テンポを固定（既定は入力 MIDI のテンポマップを継承。テンポチェンジも保持）")


def _tempo_map(args, mf: mido.MidiFile | None) -> TempoMap:
    """--tempo があればそれ一定、無ければ入力 MIDI のテンポマップ（DAW 上で小節グリッドを揃えるため）。"""
    if args.tempo is not None:
        return TempoMap.constant(mf.ticks_per_beat if mf is not None else 960, args.tempo)
    if mf is not None:
        return TempoMap.from_midifile(mf)
    return TempoMap.constant(960, 120.0)


def _key_arg(args, default="auto"):
    if args.no_key_bias:
        return None
    if args.key:
        return parse_key(args.key)
    return default


def _prepare(args, notes: list[Note]):
    profile = load_profile(args.profile)
    if args.vibrato_lane:
        profile.output.vibrato_lane = args.vibrato_lane
    if args.dyn_cc is not None:
        profile.dynamics.cc_number = args.dyn_cc
    if args.mode == "single":
        notes = make_monophonic(notes, overlap_s=args.legato_overlap_ms / 1000.0)
    contour = generate_contour(notes, profile, seed=args.seed, amount=args.amount, lookahead=not args.no_lookahead,
                               key=_key_arg(args))
    return profile, contour


def cmd_profiles(args) -> int:
    for name in list_builtin_profiles():
        p = load_profile(name)
        print(f"{name:22s} {p.instrument:10s} {p.style:10s} v{p.version}  {p.source}")
    return 0


def cmd_render(args) -> int:
    notes, mf = load_midi_notes(args.input, track=args.track, channel=args.channel)
    if not notes:
        print("音符が見つかりません", file=sys.stderr)
        return 1
    profile, contour = _prepare(args, notes)
    keep = args.track is not None and not args.only_track
    render_midi(contour, profile, args.output, mode=args.mode, bend_range=args.bend_range,
                legato_overlap_s=args.legato_overlap_ms / 1000.0, max_events_per_s=args.max_events_per_s,
                tempo_map=_tempo_map(args, mf), dynamics=not args.no_dynamics, timing=not args.no_timing,
                base_file=mf if keep else None, replace_track=args.track if keep else None)
    n_vib = sum(1 for nc in contour.notes if "vibrato_rate_hz" in nc.params)
    n_port = sum(1 for nc in contour.notes if nc.params.get("portamento"))
    dyn = "off" if args.no_dynamics or not profile.dynamics.enabled else f"CC{profile.dynamics.cc_number}"
    key = key_name(*contour.key) if contour.key else "-"
    print(f"{len(notes)} 音符 → {args.output}  (profile={profile.name}, mode={args.mode}, key {key}, vibrato {n_vib}, portamento {n_port}, dynamics {dyn})")
    return 0


def cmd_info(args) -> int:
    rows = describe_midi(args.input)
    mf = mido.MidiFile(args.input)
    tm = TempoMap.from_midifile(mf)
    print(f"{args.input}: type {mf.type}, {mf.ticks_per_beat} ticks/beat, tempo {tm.initial_bpm:.2f} bpm"
          + (f" (+{len(tm.changes) - 1} 変化)" if len(tm.changes) > 1 else ""))
    print(f"{'track':>5}  {'notes':>5}  {'ch':<8} {'range':<9} {'start':>7} {'end':>7}  name")
    for r in rows:
        rng = f"{r['pitch_range'][0]}-{r['pitch_range'][1]}" if r["pitch_range"] else "-"
        ch = ",".join(str(c + 1) for c in r["channels"]) or "-"
        st = f"{r['start_s']:.2f}" if r["start_s"] is not None else "-"
        print(f"{r['track']:>5}  {r['notes']:>5}  {ch:<8} {rng:<9} {st:>7} {r['end_s']:>7.2f}  {r['name']}")
    print("render で使うトラックは --track N（0 始まり）で指定。他のトラックは保持される")
    return 0


def cmd_dump(args) -> int:
    notes, _ = load_midi_notes(args.input, track=args.track, channel=args.channel)
    profile, contour = _prepare(args, notes)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("time_s,note,cents,intonation,transition,attack,vibrato,drift,release,jitter,dyn\n")
        for nc in contour.notes:
            for k, ti in enumerate(nc.t):
                parts = ",".join(f"{nc.parts[p][k]:.2f}" for p in ("intonation", "transition", "attack", "vibrato", "drift", "release", "jitter"))
                f.write(f"{nc.note.onset + ti:.4f},{nc.note.pitch},{nc.cents[k]:.2f},{parts},{nc.dyn[k]:.3f}\n")
    print(f"→ {args.output}")
    return 0


def cmd_analyze(args) -> int:
    x, sr = read_wav(args.input)
    notes, track = analyze_audio(x, sr, hop_s=args.hop_ms / 1000.0, fmin=args.fmin, fmax=args.fmax)
    if not notes:
        print("音符を検出できませんでした（無音・ノイズ・多声の可能性）", file=sys.stderr)
        return 1
    base = load_profile(args.base) if args.base else None
    name = args.name or Path(args.input).stem
    profile = build_profile(notes, base=base, name=name, instrument=args.instrument or (base.instrument if base else "unknown"),
                            style=args.style or (base.style if base else "unknown"), hop_s=track.hop_s)
    profile.save(args.output)
    print(f"{len(notes)} 音符を解析 → {args.output}")
    print(json.dumps(profile.stats, ensure_ascii=False))
    if args.notes_json:
        rows = [{"pitch": n.pitch, "onset": round(n.onset, 4), "offset": round(n.offset, 4), **n.params} for n in notes]
        Path(args.notes_json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"音符ごとの推定値 → {args.notes_json}")
    return 0


def demo_notes() -> list[Note]:
    """デモ用の短いフレーズ（ハ長調、レガートと跳躍と長音を含む）。"""
    seq = [(67, 0.5), (69, 0.5), (71, 1.0), (72, 0.5), (74, 1.5), (72, 0.25), (71, 0.25), (69, 0.5), (67, 2.0),
           None, (64, 0.5), (65, 0.5), (67, 1.0), (72, 1.5), (71, 0.5), (69, 0.5), (67, 2.5)]
    notes: list[Note] = []
    t = 0.0
    for item in seq:
        if item is None:
            t += 0.6
            continue
        pitch, dur = item
        notes.append(Note(pitch=pitch, onset=t, duration=dur, velocity=96))
        t += dur
    return notes


def cmd_demo(args) -> int:
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mf = None
    if args.input:
        notes, mf = load_midi_notes(args.input)
    else:
        notes = demo_notes()
    profile, contour = _prepare(args, notes)
    flat_args = argparse.Namespace(**{**vars(args), "amount": 0.0})
    _, flat = _prepare(flat_args, notes)
    tag = profile.name
    render_kw = dict(mode=args.mode, bend_range=args.bend_range, tempo_map=_tempo_map(args, mf),
                     legato_overlap_s=args.legato_overlap_ms / 1000.0, max_events_per_s=args.max_events_per_s,
                     dynamics=not args.no_dynamics, timing=not args.no_timing)
    render_midi(contour, profile, out / f"demo_{tag}.mid", **render_kw)
    render_midi(flat, profile, out / "demo_static.mid", **render_kw)
    write_wav(out / f"demo_{tag}.wav", synthesize(contour))
    write_wav(out / "demo_static.wav", synthesize(flat))
    print(f"→ {out}/demo_static.(wav|mid) と {out}/demo_{tag}.(wav|mid)  を聴き比べてください")
    return 0


def cmd_ports(args) -> int:
    try:
        from .realtime import list_ports
        ins, outs = list_ports()
    except Exception as e:  # rtmidi 未インストールなど
        print(f"MIDI ポートを列挙できません: {e}\n  pip install python-rtmidi を実行してください", file=sys.stderr)
        return 1
    print("入力:")
    for n in ins:
        print("  ", n)
    print("出力:")
    for n in outs:
        print("  ", n)
    return 0


def cmd_live(args) -> int:
    try:
        from .realtime import RealtimeTracer, run_live
    except Exception as e:
        print(f"リアルタイム機能を読み込めません: {e}", file=sys.stderr)
        return 1
    profile = load_profile(args.profile)
    if args.vibrato_lane:
        profile.output.vibrato_lane = args.vibrato_lane

    def factory(send):
        return RealtimeTracer(profile=profile, send=send, mode=args.mode, bend_range=args.bend_range,
                              channel=args.out_channel, seed=args.seed, amount=args.amount,
                              legato_overlap_s=args.legato_overlap_ms / 1000.0, passthrough=not args.no_passthrough,
                              dynamics=not args.no_dynamics, key=_key_arg(args, default=None))

    run_live(factory, args.inport, args.outport, in_channel=args.in_channel, verbose=args.verbose)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pitchtrace", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("profiles", help="組み込みプロファイル一覧").set_defaults(func=cmd_profiles)

    i = sub.add_parser("info", help="MIDI ファイルのトラック一覧")
    i.add_argument("input"); i.set_defaults(func=cmd_info)

    r = sub.add_parser("render", help="MIDI に表情を付ける")
    r.add_argument("input"); r.add_argument("output")
    r.add_argument("--track", type=int, default=None, help="処理するトラック（0 始まり）。指定時は他トラックを保持して差し替える")
    r.add_argument("--channel", type=int, default=None, help="処理する MIDI チャンネル（0 始まり）")
    r.add_argument("--only-track", action="store_true", help="--track 指定時に他トラックを捨てて単独ファイルにする")
    _add_render_opts(r); r.set_defaults(func=cmd_render)

    d = sub.add_parser("dump", help="カーブを CSV に書き出す")
    d.add_argument("input"); d.add_argument("output")
    d.add_argument("--track", type=int, default=None); d.add_argument("--channel", type=int, default=None)
    _add_render_opts(d); d.set_defaults(func=cmd_dump)

    a = sub.add_parser("analyze", help="ソロ録音からプロファイルを作る")
    a.add_argument("input", help="WAV（モノラル推奨・単旋律・無伴奏）")
    a.add_argument("-o", "--output", required=True, help="出力プロファイル JSON")
    a.add_argument("--base", default=None, help="推定できない項目の既定値に使う組み込みプロファイル")
    a.add_argument("--name", default=None); a.add_argument("--instrument", default=None); a.add_argument("--style", default=None)
    a.add_argument("--hop-ms", type=float, default=5.0)
    a.add_argument("--fmin", type=float, default=80.0); a.add_argument("--fmax", type=float, default=1500.0)
    a.add_argument("--notes-json", default=None, help="音符ごとの推定値も JSON で書き出す")
    a.set_defaults(func=cmd_analyze)

    sub.add_parser("ports", help="MIDI ポート一覧").set_defaults(func=cmd_ports)

    lv = sub.add_parser("live", help="リアルタイム処理（仮想 MIDI ポート）")
    lv.add_argument("--in", dest="inport", default="virtual", help="入力ポート名（部分一致）。'virtual' で 'PitchTrace In' を作る")
    lv.add_argument("--out", dest="outport", default="virtual", help="出力ポート名（部分一致）。'virtual' で 'PitchTrace Out' を作る")
    lv.add_argument("--in-channel", type=int, default=None, help="このチャンネルの入力だけを処理（0 始まり）")
    lv.add_argument("--out-channel", type=int, default=0, help="single モードの出力チャンネル（0 始まり）")
    lv.add_argument("--no-passthrough", action="store_true", help="ノート以外のメッセージを通さない")
    lv.add_argument("--verbose", "-v", action="store_true")
    _add_render_opts(lv); lv.set_defaults(func=cmd_live)

    m = sub.add_parser("demo", help="A/B 用の WAV と MIDI を作る")
    m.add_argument("out_dir"); m.add_argument("--input", default=None, help="MIDI（省略時は内蔵フレーズ）")
    _add_render_opts(m); m.set_defaults(func=cmd_demo)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

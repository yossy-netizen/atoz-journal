"""可視化（研究・デバッグ用）。matplotlib は任意依存。

- IGF: 生 F0（MIDI 換算）・正規化カーブ・信頼度・ノート境界・遷移境界
- Contour: 生成したカーブ（成分別）とダイナミクス
両方を渡すと上下に並べる。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .generate import Contour


def _mpl():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("plot には matplotlib が必要です: pip install matplotlib") from e


def plot_igf(ax, igf: dict, ax_conf=None) -> None:
    for n in igf["notes"]:
        t = np.asarray(n["curve"]["time_sec"], dtype=float)
        c = np.asarray([np.nan if v is None else v for v in n["curve"]["cents"]], dtype=float)
        base = n["midi_note"] * 100.0
        ax.plot([n["start_sec"], n["end_sec"]], [base, base], color="0.6", lw=1.0)
        ax.plot(t, base + c, color="tab:blue", lw=1.0)
        ax.axvline(n["start_sec"], color="0.8", lw=0.5)
        tr = n.get("transition_in")
        if tr and tr.get("start_sec") is not None:
            ax.axvspan(tr["start_sec"], tr["end_sec"], color="tab:orange", alpha=0.2, lw=0)
        if ax_conf is not None:
            ax_conf.plot(t, n["curve"]["confidence"], color="tab:green", lw=0.8)
    ax.set_ylabel("pitch (MIDI × 100)")
    ax.set_title(f"IGF: {igf.get('instrument')}  tuning A={igf['source'].get('reference_tuning_hz')} Hz  key {igf['key']['tonic']}:{igf['key']['mode']}")
    if ax_conf is not None:
        ax_conf.set_ylim(0, 1.05)
        ax_conf.set_ylabel("confidence")


def plot_contour(ax, contour: Contour, ax_dyn=None, components: bool = True) -> None:
    for nc in contour.notes:
        base = nc.note.pitch * 100.0
        t = nc.note.onset + nc.t
        ax.plot([nc.note.onset, nc.note.offset], [base, base], color="0.6", lw=1.0)
        ax.plot(t, base + nc.cents, color="tab:red", lw=1.0)
        if components:
            ax.plot(t, base + nc.parts["intonation"] + nc.parts["transition"] + nc.parts["attack"], color="tab:orange", lw=0.6, alpha=0.7)
        if ax_dyn is not None and nc.dyn is not None:
            ax_dyn.plot(t, nc.dyn, color="tab:purple", lw=0.8)
    ax.set_ylabel("pitch (MIDI × 100)")
    ax.set_title("generated contour (red) / intonation + transition + attack (orange)")
    if ax_dyn is not None:
        ax_dyn.set_ylim(0, 1.05)
        ax_dyn.set_ylabel("dynamics")


def save_plot(path: str | Path, igf: dict | None = None, contour: Contour | None = None, t_range: tuple[float, float] | None = None) -> None:
    plt = _mpl()
    rows = []
    if igf is not None:
        rows += [("igf", 3), ("conf", 1)]
    if contour is not None:
        rows += [("contour", 3), ("dyn", 1)]
    if not rows:
        raise ValueError("IGF か Contour のどちらかが必要です")
    fig, axes = plt.subplots(len(rows), 1, figsize=(14, 2.2 * sum(h for _, h in rows) / 1.5), sharex=True,
                             gridspec_kw={"height_ratios": [h for _, h in rows]})
    axes = np.atleast_1d(axes)
    i = 0
    if igf is not None:
        plot_igf(axes[i], igf, axes[i + 1])
        i += 2
    if contour is not None:
        plot_contour(axes[i], contour, axes[i + 1])
        i += 2
    axes[-1].set_xlabel("time (s)")
    if t_range:
        axes[-1].set_xlim(*t_range)
    fig.tight_layout()
    fig.savefig(str(path), dpi=110)
    plt.close(fig)

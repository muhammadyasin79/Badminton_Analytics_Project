"""
Backend wrapper around the existing badminton analysis scripts.

It runs the two proven pipelines as subprocesses (so their tuned algorithms are
reused verbatim), pointed at an arbitrary input video + output dir via env vars:

  1. color_id_weixin.py      -> annotated video + per-color-identity player table
  2. pose_analytics_weixin.py -> swing-timeline + feature-distribution charts

then assembles a single summary dict (overview / players / media / advice),
the same shape the web/mobile front-ends consume.

Progress is surfaced through an optional callback so the API can show a live
progress bar while the (multi-minute) GPU work runs.
"""
import os
import re
import sys
import csv
import json
import shutil
import subprocess
from typing import Callable, Dict, Any, List, Optional

# project root = parent of this backend/ dir; scripts + model live there
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COLOR_SCRIPT = os.path.join(ROOT, "color_id_weixin.py")
POSE_SCRIPT = os.path.join(ROOT, "pose_analytics_weixin.py")

# progress callback signature: (stage_label: str, fraction: float in [0,1])
ProgressCb = Optional[Callable[[str, float], None]]

_PROG_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")


def _ffprobe_duration(video_path: str) -> Optional[float]:
    """Clip duration in seconds via ffprobe (avoids importing cv2 here)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, check=True).stdout.strip()
        return round(float(out), 1)
    except Exception:
        return None


def _run_script(script: str, env: Dict[str, str], cwd: str,
                report: Callable[[float], None]) -> None:
    """Run one analysis script, streaming its stdout to parse `fi/N` progress.

    `report(frac)` is called with frac in [0,1] for THIS script's own progress.
    The tracking pass prints `  fi/N`; the (silent) render pass that follows is
    covered by holding near the top of the band until the process exits.
    """
    proc = subprocess.Popen(
        [sys.executable, script],  # same interpreter (venv), not PATH's python3
        cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)
    last_frac = 0.0
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        m = _PROG_RE.search(line)
        if m:
            cur, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                # tracking pass = first ~85% of this script; render fills the rest
                last_frac = min(0.85, cur / total * 0.85)
                report(last_frac)
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"{os.path.basename(script)} exited with code {code}")
    report(1.0)


def _read_players(out_dir: str) -> List[Dict[str, Any]]:
    players: List[Dict[str, Any]] = []
    summ = os.path.join(out_dir, "color_summary.csv")
    if not os.path.exists(summ):
        return players
    with open(summ) as f:
        for r in csv.DictReader(f):
            def g(k, cast=float):
                v = r.get(k, "")
                if v in ("", "None", None):
                    return None
                try:
                    return cast(v)
                except ValueError:
                    return None
            players.append({
                "identity": r.get("identity", "球员"),
                "seconds_present": g("seconds_present"),
                "swings": g("swings", int) or 0,
                "swings_per_min": g("swings_per_min"),
                "max_arm_extension": g("max_arm_extension"),
                "mean_arm_extension": g("mean_arm_extension"),
                "overhead_pct": g("overhead_pct"),
                "mean_stance_width": g("mean_stance_width"),
            })
    return players


def _count_rows(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        return max(0, sum(1 for _ in f) - 1)  # minus header


def run_analysis(video_path: str, out_dir: str,
                 progress_cb: ProgressCb = None,
                 device: Optional[str] = None) -> Dict[str, Any]:
    """Run the full analysis on `video_path`, writing artifacts into `out_dir`.

    Returns the assembled summary dict. Also writes `out_dir/summary.json`.
    Media file names in the returned `media` are RELATIVE to `out_dir`.
    """
    os.makedirs(out_dir, exist_ok=True)
    device = device or os.environ.get("BAD_DEVICE", "mps")

    from advice import build_advice  # local import; same dir on sys.path

    def emit(stage: str, frac: float):
        if progress_cb:
            progress_cb(stage, max(0.0, min(1.0, frac)))

    base_env = dict(os.environ)
    base_env.update({
        "BAD_VIDEO": os.path.abspath(video_path),
        "BAD_OUT": os.path.abspath(out_dir),
        "BAD_DEVICE": device,
    })

    # ---- stage 1: color-id (annotated video + player table) -> 0..50% ----
    emit("识别球员与挥拍 (1/2)", 0.02)
    _run_script(COLOR_SCRIPT, base_env, ROOT,
                lambda f: emit("识别球员与挥拍 (1/2)", 0.02 + f * 0.48))

    # ---- stage 2: pose analytics (charts) -> 50..95% ----
    emit("分析姿态并生成图表 (2/2)", 0.50)
    _run_script(POSE_SCRIPT, base_env, ROOT,
                lambda f: emit("分析姿态并生成图表 (2/2)", 0.50 + f * 0.45))

    # ---- assemble summary -> 95..100% ----
    emit("整理结果", 0.96)
    players = _read_players(out_dir)
    total_swings = _count_rows(os.path.join(out_dir, "color_swing_events.csv"))

    media = {}
    for key, fname in (("video", "annotated_weixin_colorID_audio.mp4"),
                       ("swing_timeline", "swing_timeline.png"),
                       ("feature_dist", "pose_feature_dist.png")):
        media[key] = fname if os.path.exists(os.path.join(out_dir, fname)) else None
    # fall back to the no-audio render if muxing failed
    if media["video"] is None and os.path.exists(os.path.join(out_dir, "annotated_weixin_colorID.mp4")):
        media["video"] = "annotated_weixin_colorID.mp4"

    summary = {
        "overview": {
            "title": "🏸 羽毛球姿态分析",
            "subtitle": "基于球员姿态的可靠分析(手持/双打素材)",
            "duration_s": _ffprobe_duration(video_path),
            "num_players": len(players),
            "total_swings": total_swings,
        },
        "players": players,
        "media": media,
        "advice": build_advice(players),
    }

    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    emit("完成", 1.0)
    return summary


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Run badminton analysis on a video.")
    ap.add_argument("video")
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, "results_cli"))
    ap.add_argument("-d", "--device", default=os.environ.get("BAD_DEVICE", "mps"))
    args = ap.parse_args()
    res = run_analysis(args.video, args.out,
                       progress_cb=lambda s, f: print(f"[{f*100:5.1f}%] {s}"),
                       device=args.device)
    print(json.dumps(res, ensure_ascii=False, indent=2))

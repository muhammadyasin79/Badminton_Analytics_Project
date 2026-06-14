"""
Heuristic, auto-generated coaching advice from per-player pose metrics.

The original web demo shipped hand-authored advice tuned to one specific clip.
For arbitrary uploaded videos we cannot hand-write conclusions, so we derive a
few coaching pointers from the measured metrics using simple thresholds.

Every metric here is camera-pan/zoom-normalized (torso-length units), matching
how color_id_weixin.py / pose_analytics_weixin.py compute them. All advice is
explicitly framed as heuristic guidance, and we always keep the important
"down-smash vs flat-drive" caveat so users don't over-read the numbers.
"""
from typing import List, Dict, Any, Optional


def _num(x: Optional[float]) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _fmt(x: Optional[float], suffix: str = "") -> str:
    return "—" if x is None else f"{x:g}{suffix}"


def build_advice(players: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Return a list of {title, body} advice cards derived from `players`.

    `players` are the per-identity aggregates (identity, swings_per_min,
    mean_arm_extension, max_arm_extension, overhead_pct, mean_stance_width, ...).
    """
    cards: List[Dict[str, str]] = []

    # ---- overall play style ----
    paces = [p for p in (_num(pl.get("swings_per_min")) for pl in players) if p is not None]
    avg_pace = sum(paces) / len(paces) if paces else None
    ohs = [o for o in (_num(pl.get("overhead_pct")) for pl in players) if o is not None]
    avg_oh = sum(ohs) / len(ohs) if ohs else None

    overall = []
    if avg_pace is not None:
        tempo = "快节奏" if avg_pace >= 45 else ("中等节奏" if avg_pace >= 25 else "偏慢节奏")
        overall.append(f"两名主力平均挥拍约 {avg_pace:.0f} 次/分,属于{tempo}对抗。")
    if avg_oh is not None:
        if avg_oh < 15:
            overall.append(
                f"过顶击球占比偏低(平均 {avg_oh:.0f}%),说明真正的后场起跳进攻较少、"
                "以半场平抽对拉为主。建议加入完整四方球与攻防转换训练,主动跳出半场对拉。")
        else:
            overall.append(
                f"过顶击球占比 {avg_oh:.0f}%,有一定高位进攻参与度,可继续强化进攻的连续性与质量。")
    if overall:
        cards.append({"title": "整体打法", "body": "".join(overall)})

    # ---- per-player, comparative pointers ----
    # Rank by power proxy (mean arm extension) and footwork proxy (stance width)
    def by(metric):
        vals = [(pl, _num(pl.get(metric))) for pl in players]
        vals = [(pl, v) for pl, v in vals if v is not None]
        return sorted(vals, key=lambda t: t[1])

    ext_rank = by("mean_arm_extension")
    stance_rank = by("mean_stance_width")

    for pl in players:
        ident = pl.get("identity", "球员")
        tips = []
        ext = _num(pl.get("mean_arm_extension"))
        mx = _num(pl.get("max_arm_extension"))
        stance = _num(pl.get("mean_stance_width"))
        oh = _num(pl.get("overhead_pct"))

        # power: weakest extension player gets the swing-chain pointer
        if ext_rank and len(ext_rank) >= 2 and ext_rank[0][0] is pl:
            stronger = ext_rank[-1][0].get("identity", "对手")
            tips.append(
                f"① 爆发性进攻偏弱:平均手臂伸展 {_fmt(ext)} 低于{stronger},挥拍峰值 {_fmt(mx)}。"
                "专练杀球发力链(蹬地→转髋→转肩→小臂内旋鞭打),强调接触瞬间加速。")

        # footwork: narrowest stance player gets the footwork pointer
        if stance_rank and len(stance_rank) >= 2 and stance_rank[0][0] is pl:
            wider = stance_rank[-1][0]
            wider_v = _num(wider.get("mean_stance_width"))
            tips.append(
                f"② 步幅偏窄(平均 {_fmt(stance)} < {_fmt(wider_v)}):多练分腿垫步与米字步,"
                "加大弓步、降低准备重心,提升到位率。")

        # attack initiative: low overhead share
        if oh is not None and oh < 12:
            tips.append(
                f"③ 主动高位进攻偏少(过顶 {oh:.0f}%):把被动接平球更多转成主动抢高点下压,"
                "提高进攻果断性。")

        if not tips:
            tips.append("各项指标较均衡,建议保持并在实战中提升进攻连续性与落点控制。")

        cards.append({"title": f"{ident}球员 · 建议", "body": "".join(tips)})

    # ---- always-on caveat (kept verbatim from the original analysis) ----
    cards.append({
        "title": "⚠️ 重要说明:下压 vs 平抽",
        "body": (
            "本分析只测了击球高度(过顶%)与手腕速度(强度),并未真正区分'下压扣杀'与'平抽'。"
            "二者在这两个指标里天生分不开,且斜向手持机位会因透视压缩进一步混淆。"
            "因此涉及击球性质的判断仅供参考。要可靠区分,需可靠的羽毛球轨迹或侧向/固定高位机位。"),
    })
    # general heuristic disclaimer
    cards.append({
        "title": "说明",
        "body": "以上建议由指标阈值自动生成,仅供参考,具体训练请结合教练判断与更多素材。",
    })
    return cards

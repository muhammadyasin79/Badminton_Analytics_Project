import React from "react";
import { View, Text, Image, StyleSheet, ScrollView } from "react-native";
import { useVideoPlayer, VideoView } from "expo-video";
import { videoUrl, chartUrl } from "./api";

const METRICS = [
  ["出现时长", (p) => fmt(p.seconds_present, "s")],
  ["挥拍次数", (p) => fmt(p.swings)],
  ["挥拍/分钟", (p) => fmt(p.swings_per_min)],
  ["最大手臂伸展", (p) => fmt(p.max_arm_extension)],
  ["平均手臂伸展", (p) => fmt(p.mean_arm_extension)],
  ["过顶时间%", (p) => fmt(p.overhead_pct, "%")],
  ["平均步幅", (p) => fmt(p.mean_stance_width)],
];

function fmt(v, suffix = "") {
  if (v === null || v === undefined) return "—";
  return `${v}${suffix}`;
}

function badgeColor(identity) {
  if (identity && identity.indexOf("红") >= 0) return "#c0392b";
  if (identity && identity.indexOf("白") >= 0) return "#7f8c8d";
  if (identity && identity.indexOf("蓝") >= 0) return "#2980b9";
  return "#555";
}

export default function Result({ apiBase, jobId, summary }) {
  const player = useVideoPlayer(videoUrl(apiBase, jobId), (p) => {
    p.loop = false;
  });

  const o = summary.overview || {};
  const players = summary.players || [];
  const advice = summary.advice || [];

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
      {/* overview */}
      <Text style={styles.h1}>{o.title || "羽毛球姿态分析"}</Text>
      {!!o.subtitle && <Text style={styles.sub}>{o.subtitle}</Text>}
      <View style={styles.stats}>
        <Stat num={`${o.duration_s ?? "—"}s`} lab="视频时长" />
        <Stat num={`${o.num_players ?? "—"}`} lab="主力球员" />
        <Stat num={`${o.total_swings ?? "—"}`} lab="总挥拍数" />
      </View>

      {/* annotated video */}
      <Card title="标注视频">
        <Text style={styles.hint}>
          彩框 = 按上衣颜色锁定的两名主力;橙色为骨架;框变红并显示 SWING! 表示一次挥拍。
        </Text>
        <VideoView
          player={player}
          style={styles.video}
          allowsFullscreen
          nativeControls
          contentFit="contain"
        />
      </Card>

      {/* players comparison */}
      <Card title="球员对比">
        <View style={styles.row}>
          <Text style={[styles.cell, styles.metricName]} />
          {players.map((p, i) => (
            <View key={i} style={[styles.cell, styles.center]}>
              <View style={[styles.badge, { backgroundColor: badgeColor(p.identity) }]}>
                <Text style={styles.badgeText}>{p.identity}</Text>
              </View>
            </View>
          ))}
        </View>
        {METRICS.map(([name, fn], r) => (
          <View key={r} style={[styles.row, r % 2 ? styles.rowAlt : null]}>
            <Text style={[styles.cell, styles.metricName]}>{name}</Text>
            {players.map((p, i) => (
              <Text key={i} style={[styles.cell, styles.center, styles.value]}>
                {fn(p)}
              </Text>
            ))}
          </View>
        ))}
      </Card>

      {/* charts */}
      <Card title="图表">
        <Chart apiBase={apiBase} jobId={jobId} name="swing_timeline"
          caption="挥拍时间线(手腕速度 + 挥拍事件)" available={!!summary.media?.swing_timeline} />
        <Chart apiBase={apiBase} jobId={jobId} name="feature_dist"
          caption="特征分布(手臂伸展 / 步幅 / 过顶占比)" available={!!summary.media?.feature_dist} />
      </Card>

      {/* advice */}
      <Card title="专业建议">
        {advice.map((a, i) => {
          const warn = a.title && a.title.indexOf("⚠") >= 0;
          return (
            <View key={i} style={[styles.advice, warn ? styles.adviceWarn : null]}>
              <Text style={styles.adviceTitle}>{a.title}</Text>
              <Text style={styles.adviceBody}>{a.body}</Text>
            </View>
          );
        })}
      </Card>
      <View style={{ height: 28 }} />
    </ScrollView>
  );
}

function Stat({ num, lab }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statNum}>{num}</Text>
      <Text style={styles.statLab}>{lab}</Text>
    </View>
  );
}

function Card({ title, children }) {
  return (
    <View style={styles.card}>
      <Text style={styles.h2}>{title}</Text>
      {children}
    </View>
  );
}

function Chart({ apiBase, jobId, name, caption, available }) {
  if (!available) return <Text style={styles.hint}>未找到图表:{caption}</Text>;
  return (
    <View style={{ marginBottom: 14 }}>
      <Image
        source={{ uri: chartUrl(apiBase, jobId, name) }}
        style={styles.chart}
        resizeMode="contain"
      />
      <Text style={styles.caption}>{caption}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: "#0f1420" },
  content: { padding: 16 },
  h1: { color: "#fff", fontSize: 24, fontWeight: "700", textAlign: "center", marginTop: 8 },
  sub: { color: "#9aa5b1", textAlign: "center", marginTop: 4, marginBottom: 12 },
  stats: { flexDirection: "row", justifyContent: "space-between", marginVertical: 12 },
  stat: { flex: 1, backgroundColor: "#1b2333", borderRadius: 12, paddingVertical: 14, marginHorizontal: 4, alignItems: "center" },
  statNum: { color: "#6ea8fe", fontSize: 22, fontWeight: "700" },
  statLab: { color: "#9aa5b1", fontSize: 12, marginTop: 2 },
  card: { backgroundColor: "#161d2b", borderRadius: 14, padding: 14, marginTop: 14 },
  h2: { color: "#fff", fontSize: 18, fontWeight: "700", marginBottom: 10 },
  hint: { color: "#8b94a3", fontSize: 12, marginBottom: 10, lineHeight: 18 },
  video: { width: "100%", aspectRatio: 16 / 9, backgroundColor: "#000", borderRadius: 10 },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 8 },
  rowAlt: { backgroundColor: "#1b2333", borderRadius: 8 },
  cell: { flex: 1, paddingHorizontal: 6 },
  metricName: { color: "#9aa5b1", fontSize: 13, flex: 1.3 },
  center: { alignItems: "center", justifyContent: "center" },
  value: { color: "#e6e9ee", fontSize: 14, textAlign: "center" },
  badge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 10 },
  badgeText: { color: "#fff", fontSize: 12, fontWeight: "600" },
  chart: { width: "100%", height: 180, backgroundColor: "#fff", borderRadius: 8 },
  caption: { color: "#8b94a3", fontSize: 12, marginTop: 6, textAlign: "center" },
  advice: { backgroundColor: "#1b2333", borderRadius: 10, padding: 12, marginBottom: 10, borderLeftWidth: 3, borderLeftColor: "#6ea8fe" },
  adviceWarn: { borderLeftColor: "#e0a800", backgroundColor: "#2a2410" },
  adviceTitle: { color: "#fff", fontSize: 15, fontWeight: "700", marginBottom: 6 },
  adviceBody: { color: "#c7cdd6", fontSize: 13, lineHeight: 20 },
});

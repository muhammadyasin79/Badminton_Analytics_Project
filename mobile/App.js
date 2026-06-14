import React, { useState, useRef, useCallback, useEffect } from "react";
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator,
  SafeAreaView, Platform, StatusBar as RNStatusBar,
} from "react-native";
import { StatusBar } from "expo-status-bar";
import * as ImagePicker from "expo-image-picker";
import { DEFAULT_API_BASE, POLL_INTERVAL_MS } from "./src/config";
import { uploadVideo, getJob, getResult } from "./src/api";
import Result from "./src/Result";

// app phases
const IDLE = "idle";
const UPLOADING = "uploading";
const PROCESSING = "processing";
const DONE = "done";
const ERROR = "error";

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [phase, setPhase] = useState(IDLE);
  const [uploadPct, setUploadPct] = useState(0);
  const [stage, setStage] = useState("");
  const [progress, setProgress] = useState(0);
  const [jobId, setJobId] = useState(null);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const pollRef = useRef(null);

  const cleanBase = useCallback(() => apiBase.trim().replace(/\/+$/, ""), [apiBase]);

  const reset = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
    setPhase(IDLE); setUploadPct(0); setStage(""); setProgress(0);
    setJobId(null); setSummary(null); setError("");
  };

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const pickAndAnalyze = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        setError("需要相册权限才能选择视频"); setPhase(ERROR); return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["videos"],
        allowsMultipleSelection: false,
        quality: 1,
      });
      if (res.canceled || !res.assets?.length) return;
      const asset = res.assets[0];
      const name = asset.fileName || `clip_${Date.now()}.mp4`;

      // ---- upload ----
      setError(""); setPhase(UPLOADING); setUploadPct(0);
      const { job_id } = await uploadVideo(
        cleanBase(), asset.uri, name, (f) => setUploadPct(f));
      setJobId(job_id);

      // ---- poll processing ----
      setPhase(PROCESSING); setProgress(0); setStage("排队中");
      pollRef.current = setInterval(async () => {
        try {
          const j = await getJob(cleanBase(), job_id);
          setStage(j.stage || ""); setProgress(j.progress || 0);
          if (j.status === "done") {
            clearInterval(pollRef.current); pollRef.current = null;
            const s = await getResult(cleanBase(), job_id);
            setSummary(s); setPhase(DONE);
          } else if (j.status === "error") {
            clearInterval(pollRef.current); pollRef.current = null;
            setError(j.error || "分析失败"); setPhase(ERROR);
          }
        } catch (e) {
          clearInterval(pollRef.current); pollRef.current = null;
          setError(String(e.message || e)); setPhase(ERROR);
        }
      }, POLL_INTERVAL_MS);
    } catch (e) {
      setError(String(e.message || e)); setPhase(ERROR);
    }
  };

  if (phase === DONE && summary) {
    return (
      <SafeAreaView style={styles.safe}>
        <StatusBar style="light" />
        <Result apiBase={cleanBase()} jobId={jobId} summary={summary} />
        <TouchableOpacity style={styles.fab} onPress={reset}>
          <Text style={styles.fabText}>＋ 新分析</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <View style={styles.home}>
        <Text style={styles.logo}>🏸</Text>
        <Text style={styles.title}>羽毛球姿态分析</Text>
        <Text style={styles.subtitle}>上传本地 MP4,自动检测球员、挥拍与姿态指标</Text>

        <Text style={styles.label}>后端地址(你 Mac 的局域网 IP)</Text>
        <TextInput
          style={styles.input}
          value={apiBase}
          onChangeText={setApiBase}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="http://192.168.x.x:8000"
          placeholderTextColor="#5a6473"
          editable={phase === IDLE || phase === ERROR}
        />

        {(phase === IDLE || phase === ERROR) && (
          <TouchableOpacity style={styles.btn} onPress={pickAndAnalyze}>
            <Text style={styles.btnText}>选择视频并分析</Text>
          </TouchableOpacity>
        )}

        {phase === UPLOADING && (
          <Progress label={`上传中… ${Math.round(uploadPct * 100)}%`} frac={uploadPct} />
        )}

        {phase === PROCESSING && (
          <Progress label={`${stage || "处理中"}… ${Math.round(progress * 100)}%`} frac={progress} spinner />
        )}

        {phase === ERROR && !!error && (
          <Text style={styles.error}>⚠️ {error}</Text>
        )}

        {(phase === UPLOADING || phase === PROCESSING) && (
          <Text style={styles.note}>分析约需 2~5 分钟(逐帧检测),请保持 App 在前台。</Text>
        )}
      </View>
    </SafeAreaView>
  );
}

function Progress({ label, frac, spinner }) {
  return (
    <View style={styles.progressWrap}>
      <View style={styles.barBg}>
        <View style={[styles.barFill, { width: `${Math.max(3, Math.round((frac || 0) * 100))}%` }]} />
      </View>
      <View style={styles.progressRow}>
        {spinner && <ActivityIndicator color="#6ea8fe" style={{ marginRight: 8 }} />}
        <Text style={styles.progressLabel}>{label}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#0f1420", paddingTop: Platform.OS === "android" ? RNStatusBar.currentHeight : 0 },
  home: { flex: 1, justifyContent: "center", padding: 24 },
  logo: { fontSize: 56, textAlign: "center" },
  title: { color: "#fff", fontSize: 26, fontWeight: "800", textAlign: "center", marginTop: 8 },
  subtitle: { color: "#9aa5b1", fontSize: 14, textAlign: "center", marginTop: 8, marginBottom: 28, lineHeight: 20 },
  label: { color: "#8b94a3", fontSize: 12, marginBottom: 6 },
  input: { backgroundColor: "#1b2333", color: "#e6e9ee", borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, marginBottom: 20 },
  btn: { backgroundColor: "#3b82f6", borderRadius: 12, paddingVertical: 16, alignItems: "center" },
  btnText: { color: "#fff", fontSize: 17, fontWeight: "700" },
  progressWrap: { marginTop: 8 },
  barBg: { height: 10, backgroundColor: "#1b2333", borderRadius: 6, overflow: "hidden" },
  barFill: { height: 10, backgroundColor: "#3b82f6", borderRadius: 6 },
  progressRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", marginTop: 12 },
  progressLabel: { color: "#c7cdd6", fontSize: 14 },
  note: { color: "#6b7280", fontSize: 12, textAlign: "center", marginTop: 18 },
  error: { color: "#f87171", fontSize: 14, textAlign: "center", marginTop: 18, lineHeight: 20 },
  fab: { position: "absolute", right: 18, bottom: 28, backgroundColor: "#3b82f6", paddingHorizontal: 18, paddingVertical: 12, borderRadius: 24, elevation: 4 },
  fabText: { color: "#fff", fontWeight: "700", fontSize: 15 },
});

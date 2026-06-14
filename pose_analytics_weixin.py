#!/usr/bin/env python3
"""
Pose-only analytics for the handheld/doubles WeChat clip.

All metrics are made robust to the panning camera by:
  - referencing keypoints to the player's own torso center (cancels camera pan
    + player translation), and
  - normalizing by torso length = |shoulder_mid - hip_mid| (cancels zoom/scale).
Players are tracked with ByteTrack so metrics are per-player.

No shuttle, no court calibration -> nothing here depends on those.

Outputs (results_weixin/):
  - pose_metrics.csv          : per-frame per-track normalized features
  - swing_events.csv          : detected swing (hit-motion) events per player
  - pose_summary.csv/json     : per-player aggregates
  - swing_timeline.png        : wrist-speed series + detected swings
  - pose_feature_dist.png     : extension / stance / overhead distributions
  - annotated_weixin_swings.mp4(+_audio) : video with SWING! flashes + HUD
"""
import os, json, subprocess, csv
from collections import defaultdict
import numpy as np
import cv2
from ultralytics import YOLO

ROOT = os.path.dirname(os.path.abspath(__file__))
# VIDEO / OUT / DEVICE are overridable via env vars so the backend can point this
# script at any uploaded clip + output dir. Defaults preserve standalone use.
VIDEO = os.environ.get("BAD_VIDEO", "/Users/s-fu/Downloads/Weixin Videos2026-06-09_143534_847.mp4")
OUT = os.environ.get("BAD_OUT", os.path.join(ROOT, "results_weixin"))
os.makedirs(OUT, exist_ok=True)

DEVICE = os.environ.get("BAD_DEVICE", "mps")
PERSON_CONF = 0.45
KP_CONF = 0.3
FOREGROUND_AREA_FRAC = 0.004
# COCO-17 keypoint indices
NOSE, LSH, RSH, LEL, REL, LWR, RWR, LHIP, RHIP, LANK, RANK = 0,5,6,7,8,9,10,11,12,15,16

pose_model = YOLO("yolov8s-pose.pt")

cap = cv2.VideoCapture(VIDEO)
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
FPS = cap.get(cv2.CAP_PROP_FPS) or 30.0
N = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); frame_area = W*H
print(f"Video {W}x{H} @ {FPS:.1f}fps, {N} frames")


def kp_ok(kp, conf, i):
    return conf[i] >= KP_CONF and kp[i][0] > 0 and kp[i][1] > 0


def mid(a, b):
    return (a + b) / 2.0


# ---- PASS 1: track + extract normalized pose features --------------------
# per_frame[fi] = list of dicts {id, box, kp, feats}
per_frame = defaultdict(list)
metrics_rows = []   # frame, track, norm_wrist_speed, arm_ext, stance, overhead
prev_wrist = {}     # track -> (norm_lwr, norm_rwr) from previous frame (if consecutive)
prev_frame_seen = {}  # track -> last frame index

print("Pass 1: tracking + pose features...")
fi = 0
results = pose_model.track(source=VIDEO, stream=True, conf=PERSON_CONF,
                           device=DEVICE, tracker="bytetrack.yaml", verbose=False)
for r in results:
    if r.boxes is None or r.boxes.data is None:
        fi += 1; continue
    boxes = r.boxes.xyxy.cpu().numpy()
    ids = r.boxes.id.cpu().numpy().astype(int) if r.boxes.id is not None else np.full(len(boxes), -1)
    kxy = r.keypoints.xy.cpu().numpy() if r.keypoints is not None else None
    kcf = r.keypoints.conf.cpu().numpy() if (r.keypoints is not None and r.keypoints.conf is not None) else None

    for bi, b in enumerate(boxes):
        x1, y1, x2, y2 = b[:4]
        if (x2-x1)*(y2-y1)/frame_area < FOREGROUND_AREA_FRAC:
            continue  # background person
        tid = int(ids[bi])
        if kxy is None or kcf is None:
            continue
        kp, cf = kxy[bi], kcf[bi]
        # need shoulders + hips for the body frame
        if not (kp_ok(kp,cf,LSH) and kp_ok(kp,cf,RSH) and kp_ok(kp,cf,LHIP) and kp_ok(kp,cf,RHIP)):
            per_frame[fi].append({"id": tid, "box": b[:4], "kp": kp, "cf": cf, "swing": False})
            continue
        sh_mid = mid(kp[LSH], kp[RSH]); hip_mid = mid(kp[LHIP], kp[RHIP])
        torso = np.linalg.norm(sh_mid - hip_mid)
        if torso < 1e-3:
            per_frame[fi].append({"id": tid, "box": b[:4], "kp": kp, "cf": cf, "swing": False})
            continue

        # normalized wrist positions (relative to shoulder center, in torso units)
        nlwr = (kp[LWR]-sh_mid)/torso if kp_ok(kp,cf,LWR) else None
        nrwr = (kp[RWR]-sh_mid)/torso if kp_ok(kp,cf,RWR) else None

        # wrist speed (only if same track seen in the immediately preceding frame)
        wr_speed = np.nan
        if tid in prev_wrist and prev_frame_seen.get(tid) == fi-1:
            pl, pr_ = prev_wrist[tid]
            cand = []
            if nlwr is not None and pl is not None: cand.append(np.linalg.norm(nlwr-pl))
            if nrwr is not None and pr_ is not None: cand.append(np.linalg.norm(nrwr-pr_))
            if cand: wr_speed = max(cand)*FPS  # torso-lengths per second
        prev_wrist[tid] = (nlwr, nrwr); prev_frame_seen[tid] = fi

        # arm extension = max wrist-shoulder distance / torso
        exts = []
        if kp_ok(kp,cf,LWR): exts.append(np.linalg.norm(kp[LWR]-kp[LSH])/torso)
        if kp_ok(kp,cf,RWR): exts.append(np.linalg.norm(kp[RWR]-kp[RSH])/torso)
        arm_ext = max(exts) if exts else np.nan

        # overhead: any wrist above shoulder line (smaller image-y = higher)
        overhead = False
        if kp_ok(kp,cf,LWR) and kp[LWR][1] < sh_mid[1]: overhead = True
        if kp_ok(kp,cf,RWR) and kp[RWR][1] < sh_mid[1]: overhead = True

        # stance width = ankle separation / torso
        stance = np.nan
        if kp_ok(kp,cf,LANK) and kp_ok(kp,cf,RANK):
            stance = np.linalg.norm(kp[LANK]-kp[RANK])/torso

        metrics_rows.append((fi, tid, wr_speed, arm_ext, int(overhead), stance))
        per_frame[fi].append({"id": tid, "box": b[:4], "kp": kp, "cf": cf, "swing": False,
                              "wr_speed": wr_speed, "arm_ext": arm_ext, "overhead": overhead})
    fi += 1
    if fi % 100 == 0: print(f"  {fi}/{N}")
total_frames = fi
print(f"Tracked {total_frames} frames, {len(metrics_rows)} foreground pose samples.")

# ---- swing detection per track ------------------------------------------
M = np.array([(m[0], m[1], m[2]) for m in metrics_rows], dtype=float)  # frame,track,speed
by_track = defaultdict(list)
for frame, tid, sp, *_ in metrics_rows:
    by_track[tid].append((frame, sp))

# global threshold from valid speeds
valid_sp = M[:,2][~np.isnan(M[:,2])]
if len(valid_sp) > 10:
    thr = float(np.nanmean(valid_sp) + 1.3*np.nanstd(valid_sp))
else:
    thr = 6.0
thr = max(thr, 4.0)  # floor: ignore tiny jitter (torso-lengths/sec)
print(f"Swing speed threshold: {thr:.2f} torso-lengths/s")

swing_events = []   # (track, frame, time_s, intensity)
swing_set = set()   # (frame, track)
REFRACTORY = 7      # frames (~0.23s) between swings of one player
for tid, seq in by_track.items():
    seq = sorted(seq)
    frames = [s[0] for s in seq]; speeds = [s[1] for s in seq]
    last = -999
    for i in range(1, len(seq)-1):
        sp = speeds[i]
        if np.isnan(sp): continue
        # local maximum above threshold
        if sp >= thr and sp >= (speeds[i-1] if not np.isnan(speeds[i-1]) else -1) \
           and sp >= (speeds[i+1] if not np.isnan(speeds[i+1]) else -1):
            if frames[i]-last >= REFRACTORY:
                swing_events.append((tid, frames[i], round(frames[i]/FPS,2), round(sp,2)))
                swing_set.add((frames[i], tid))
                last = frames[i]

# mark swings on per_frame for rendering (flash window)
for (frame, tid) in swing_set:
    for df in range(0, 5):  # flash for 5 frames
        for p in per_frame.get(frame+df, []):
            if p["id"] == tid:
                p["swing"] = True

print(f"Detected {len(swing_events)} swing events across {len(by_track)} tracks.")

# ---- save CSVs -----------------------------------------------------------
with open(os.path.join(OUT,"pose_metrics.csv"),"w",newline="") as f:
    w=csv.writer(f); w.writerow(["frame","track","norm_wrist_speed","arm_extension","overhead","stance_width"])
    w.writerows(metrics_rows)
with open(os.path.join(OUT,"swing_events.csv"),"w",newline="") as f:
    w=csv.writer(f); w.writerow(["track","frame","time_s","intensity"]); w.writerows(swing_events)

# ---- per-track aggregates -----------------------------------------------
agg_rows = []
present = defaultdict(int)
for frame,tid,*_ in metrics_rows: present[tid]+=1
for tid in sorted(by_track):
    rows=[m for m in metrics_rows if m[1]==tid]
    exts=[r[3] for r in rows if not np.isnan(r[3])]
    stances=[r[5] for r in rows if not np.isnan(r[5])]
    overheads=[r[4] for r in rows]
    n_sw=sum(1 for e in swing_events if e[0]==tid)
    secs=present[tid]/FPS
    agg_rows.append({
        "track": tid,
        "frames_present": present[tid],
        "seconds_present": round(secs,1),
        "swings": n_sw,
        "swings_per_min": round(n_sw/secs*60,1) if secs>0 else 0,
        "max_arm_extension": round(max(exts),2) if exts else None,
        "mean_arm_extension": round(float(np.mean(exts)),2) if exts else None,
        "overhead_pct": round(100*np.mean(overheads),1) if overheads else None,
        "mean_stance_width": round(float(np.mean(stances)),2) if stances else None,
    })
# keep the players that are actually on court (present a meaningful amount)
agg_rows = [a for a in agg_rows if a["frames_present"] >= 15]
agg_rows.sort(key=lambda a: -a["frames_present"])
with open(os.path.join(OUT,"pose_summary.json"),"w") as f:
    json.dump(agg_rows,f,indent=2,ensure_ascii=False,default=float)
with open(os.path.join(OUT,"pose_summary.csv"),"w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(agg_rows[0].keys())); w.writeheader(); w.writerows(agg_rows)
print(json.dumps(agg_rows,indent=2,ensure_ascii=False,default=float))

# ---- plots --------------------------------------------------------------
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
top_tracks = [a["track"] for a in agg_rows[:4]]
plt.figure(figsize=(13,6))
for tid in top_tracks:
    seq=sorted([(m[0],m[2]) for m in metrics_rows if m[1]==tid and not np.isnan(m[2])])
    if not seq: continue
    fr=[s[0] for s in seq]; sp=[s[1] for s in seq]
    plt.plot(fr,sp,lw=1,label=f"track {tid}")
ev_f=[e[1] for e in swing_events]; ev_s=[e[3] for e in swing_events]
plt.scatter(ev_f,ev_s,color="red",zorder=5,s=30,label="swing event")
plt.axhline(thr,color="gray",ls="--",lw=1,label=f"threshold {thr:.1f}")
plt.xlabel("frame"); plt.ylabel("norm. wrist speed (torso-lengths/s)")
plt.title("Swing detection — normalized wrist speed per player")
plt.legend(); plt.tight_layout()
plt.savefig(os.path.join(OUT,"swing_timeline.png"),dpi=120); plt.close()

fig,ax=plt.subplots(1,3,figsize=(15,4))
ext=[r[3] for r in metrics_rows if not np.isnan(r[3])]
st=[r[5] for r in metrics_rows if not np.isnan(r[5])]
ax[0].hist(ext,bins=30,color="#0a7"); ax[0].set_title("Arm extension (wrist-shoulder / torso)")
ax[1].hist(st,bins=30,color="#07a"); ax[1].set_title("Stance width (ankle gap / torso)")
oh=[a["overhead_pct"] for a in agg_rows]; tk=[str(a["track"]) for a in agg_rows]
ax[2].bar(tk,oh,color="#a40"); ax[2].set_title("Overhead time % per player"); ax[2].set_xlabel("track")
plt.tight_layout(); plt.savefig(os.path.join(OUT,"pose_feature_dist.png"),dpi=120); plt.close()

# ---- PASS 2: render annotated video from stored detections --------------
print("Pass 2: rendering swing-annotated video...")
SKELETON=[(5,7),(7,9),(6,8),(8,10),(5,6),(5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16),(0,5),(0,6)]
cap=cv2.VideoCapture(VIDEO)
writer=cv2.VideoWriter(os.path.join(OUT,"annotated_weixin_swings.mp4"),
                       cv2.VideoWriter_fourcc(*"mp4v"),FPS,(W,H))
fi=0
while True:
    ret,frame=cap.read()
    if not ret: break
    for p in per_frame.get(fi,[]):
        x1,y1,x2,y2=[int(v) for v in p["box"]]
        swing=p.get("swing",False)
        color=(0,0,255) if swing else (0,220,0)
        cv2.rectangle(frame,(x1,y1),(x2,y2),color,3 if swing else 2)
        cv2.putText(frame,f"P{p['id']}",(x1,y1-8),cv2.FONT_HERSHEY_SIMPLEX,0.6,color,2)
        kp=p["kp"]; cf=p["cf"]
        for a,c in SKELETON:
            if cf[a]>=KP_CONF and cf[c]>=KP_CONF:
                cv2.line(frame,(int(kp[a][0]),int(kp[a][1])),(int(kp[c][0]),int(kp[c][1])),(0,140,255),2)
        for j in range(len(kp)):
            if cf[j]>=KP_CONF:
                cv2.circle(frame,(int(kp[j][0]),int(kp[j][1])),3,(0,0,255),-1)
        if swing:
            cv2.putText(frame,"SWING!",(x1,y2+22),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,0,255),2)
    cv2.putText(frame,f"f{fi}",(10,25),cv2.FONT_HERSHEY_SIMPLEX,0.7,(255,255,255),2)
    writer.write(frame); fi+=1
cap.release(); writer.release()

try:
    subprocess.run(["ffmpeg","-loglevel","error","-y",
        "-i",os.path.join(OUT,"annotated_weixin_swings.mp4"),"-i",VIDEO,
        "-c:v","copy","-map","0:v:0","-map","1:a:0?","-shortest",
        os.path.join(OUT,"annotated_weixin_swings_audio.mp4")],check=True)
    print("Audio muxed.")
except Exception as e:
    print("mux failed:",e)
print("DONE ->",OUT)

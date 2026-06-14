#!/usr/bin/env python3
"""
Stabilize player identity by SHIRT COLOR (a simple appearance ReID), instead of
the tracker's volatile numeric IDs.

Pipeline:
  1. Track + pose over the clip; for every foreground player extract the torso
     shirt color (median HSV of the torso patch).
  2. KMeans(k=2) on the *strong* foreground detections -> the two near-court
     players' shirt colors. Each cluster is auto-named (白衣/红衣/...).
  3. Every foreground detection is assigned to the nearest color identity
     (with a distance gate -> "其他" for off-color / far players).
  4. Recompute swing / extension / overhead / stance per COLOR identity, which
     now stays consistent even when the tracker ID switches.

Outputs (results_weixin/):
  - color_summary.csv/json
  - color_swing_events.csv
  - annotated_weixin_colorID.mp4(+_audio)
"""
import os, csv, json, subprocess
from collections import defaultdict
import numpy as np
import cv2
from ultralytics import YOLO
from sklearn.cluster import KMeans

ROOT = os.path.dirname(os.path.abspath(__file__))
# VIDEO / OUT / DEVICE are overridable via env vars so the backend can point this
# script at any uploaded clip + output dir. Defaults preserve standalone use.
VIDEO = os.environ.get("BAD_VIDEO", "/Users/s-fu/Downloads/Weixin Videos2026-06-09_143534_847.mp4")
OUT = os.environ.get("BAD_OUT", os.path.join(ROOT, "results_weixin")); os.makedirs(OUT, exist_ok=True)
DEVICE = os.environ.get("BAD_DEVICE", "mps"); PERSON_CONF = 0.45; KP_CONF = 0.3
FG_AREA = 0.004        # foreground at all
STRONG_AREA = 0.012    # big/near -> used to learn the two shirt colors
LSH,RSH,LWR,RWR,LHIP,RHIP,LANK,RANK = 5,6,9,10,11,12,15,16

PALETTE = {  # name -> BGR
    "白衣":(235,235,235),"红衣":(40,40,200),"蓝衣":(200,90,40),
    "黑衣":(40,40,40),"黄衣":(40,210,220),"绿衣":(60,170,60),"灰衣":(130,130,130),
}
def name_color(bgr):
    b,g,r = bgr
    best,bd = None,1e9
    for nm,(pb,pg,pr) in PALETTE.items():
        d=(b-pb)**2+(g-pg)**2+(r-pr)**2
        if d<bd: bd,best=d,nm
    return best

def mid(a,b): return (a+b)/2.0
def kp_ok(kp,cf,i): return cf[i]>=KP_CONF and kp[i][0]>0 and kp[i][1]>0

def torso_color_hsv(frame, box, kp, cf):
    H,W = frame.shape[:2]
    if kp_ok(kp,cf,LSH) and kp_ok(kp,cf,RSH) and kp_ok(kp,cf,LHIP) and kp_ok(kp,cf,RHIP):
        xs=[kp[LSH][0],kp[RSH][0],kp[LHIP][0],kp[RHIP][0]]
        ys=[kp[LSH][1],kp[RSH][1],kp[LHIP][1],kp[RHIP][1]]
        x1,x2=int(min(xs)),int(max(xs)); y1,y2=int(min(ys)),int(max(ys))
        cx=(x1+x2)//2; w=max(4,(x2-x1)//3)
        x1,x2=cx-w,cx+w  # central torso strip -> avoid arms/background
    else:
        bx1,by1,bx2,by2=[int(v) for v in box]
        x1=bx1+int(0.3*(bx2-bx1)); x2=bx2-int(0.3*(bx2-bx1))
        y1=by1+int(0.15*(by2-by1)); y2=by1+int(0.45*(by2-by1))
    x1=max(0,x1); y1=max(0,y1); x2=min(W,x2); y2=min(H,y2)
    if x2-x1<3 or y2-y1<3: return None
    patch=frame[y1:y2, x1:x2]
    hsv=cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1,3).astype(float)
    # drop very dark (shadow) and tiny pixels
    m=hsv[:,2]>40
    if m.sum()<10: m=np.ones(len(hsv),bool)
    return np.median(hsv[m],axis=0)  # H(0-179),S,V

def feat(hsv):
    h=hsv[0]*2*np.pi/180.0
    return np.array([np.cos(h),np.sin(h), hsv[1]/255.0, hsv[2]/255.0])

# ---------------- PASS 1: track + collect ----------------
cap=cv2.VideoCapture(VIDEO)
W=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); Hh=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
FPS=cap.get(cv2.CAP_PROP_FPS) or 30.0; N=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); cap.release()
frame_area=W*Hh
model=YOLO("yolov8s-pose.pt")
print(f"Video {W}x{Hh} {FPS:.0f}fps {N}f")

per_frame=defaultdict(list); strong_feats=[]
cap=cv2.VideoCapture(VIDEO); fi=0
res=model.track(source=VIDEO, stream=True, conf=PERSON_CONF, device=DEVICE,
                tracker="bytetrack.yaml", verbose=False)
for r in res:
    ret,frame=cap.read()
    if not ret or r.boxes is None or r.boxes.data is None: fi+=1; continue
    boxes=r.boxes.xyxy.cpu().numpy()
    tids=r.boxes.id.cpu().numpy().astype(int) if r.boxes.id is not None else np.full(len(boxes),-1)
    kxy=r.keypoints.xy.cpu().numpy() if r.keypoints is not None else None
    kcf=r.keypoints.conf.cpu().numpy() if (r.keypoints is not None and r.keypoints.conf is not None) else None
    for bi,b in enumerate(boxes):
        x1,y1,x2,y2=b[:4]; area=(x2-x1)*(y2-y1)/frame_area
        if area<FG_AREA or kxy is None: continue
        kp,cf=kxy[bi],kcf[bi]
        hsv=torso_color_hsv(frame,b[:4],kp,cf)
        if hsv is None: continue
        rec={"box":b[:4],"kp":kp,"cf":cf,"hsv":hsv,"feat":feat(hsv),
             "area":area,"tid":int(tids[bi]),"id":None,"swing":False}
        per_frame[fi].append(rec)
        if area>=STRONG_AREA: strong_feats.append(hsv)
    fi+=1
    if fi%100==0: print(f"  {fi}/{N}")
cap.release()
total_frames=fi
print(f"collected; strong samples for color learning: {len(strong_feats)}")

# ---------------- learn 2 shirt colors ----------------
strong=np.array(strong_feats)
X=np.array([feat(h) for h in strong])
km=KMeans(n_clusters=2, n_init=10, random_state=0).fit(X)
# cluster mean color (BGR) + name
id_names={}; centers_feat=km.cluster_centers_
for c in range(2):
    mean_hsv=np.median(strong[km.labels_==c],axis=0)
    bgr=cv2.cvtColor(np.uint8([[mean_hsv]]),cv2.COLOR_HSV2BGR)[0,0]
    id_names[c]=name_color([int(bgr[0]),int(bgr[1]),int(bgr[2])])
# ensure unique names
if id_names[0]==id_names[1]: id_names[1]=id_names[1]+"2"
idents=[id_names[0],id_names[1]]
print("Learned identities:", id_names)

# per-cluster reference HSV (for saturation sanity) + tighter color gate
centers_hsv={c: np.median(strong[km.labels_==c],axis=0) for c in range(2)}
d_strong=np.min(np.linalg.norm(X[:,None,:]-centers_feat[None,:,:],axis=2),axis=1)
GATE=float(np.percentile(d_strong,80))*1.4+0.10   # tighter than before
NEAR_AREA=STRONG_AREA                              # only big/near boxes get a color id
print(f"GATE={GATE:.3f}  NEAR_AREA={NEAR_AREA}")

# ---------------- assign identity with 3 constraints ----------------
# (1) at most ONE red + ONE white per frame  (kills 3rd/4th-person-as-RED)
# (2) box must be near/large enough          (drops far opposite players)
# (3) color within gate + saturation sanity  (drops washed-out grey->red)
for fi in list(per_frame.keys()):
    recs=per_frame[fi]
    for r in recs: r["id"]="其他"
    cand=[]   # (color_dist, rec_index, cluster)
    for ri,r in enumerate(recs):
        if r["area"]<NEAR_AREA:           # constraint (2)
            continue
        d=np.linalg.norm(r["feat"][None,:]-centers_feat,axis=1)
        S=r["hsv"][1]
        for c in range(2):
            if d[c]>GATE:                 # constraint (3a): color too far
                continue
            ref_S=centers_hsv[c][1]
            if ref_S>=60 and S<0.5*ref_S: # constraint (3b): identity is colored but patch washed-out
                continue
            cand.append((float(d[c]),ri,c))
    cand.sort()                            # greedy by best color match
    used_ri=set(); used_c=set()            # constraint (1): uniqueness
    for cost,ri,c in cand:
        if ri in used_ri or c in used_c: continue
        recs[ri]["id"]=id_names[c]; used_ri.add(ri); used_c.add(c)

# ---------------- temporal smoothing: per-track majority vote ----------------
# A tracker fragment has consistent appearance, so vote its color over time and
# back-fill the frames where the per-frame step dropped it to 其他.
votes=defaultdict(lambda: defaultdict(int))
for fi in per_frame:
    for r in per_frame[fi]:
        if r["tid"]>=0 and r["id"] in idents:
            votes[r["tid"]][r["id"]] += 1
track_color={}
for tid,cnt in votes.items():
    top=max(cnt, key=cnt.get); tot=sum(cnt.values())
    if cnt[top] >= 3 and cnt[top] >= 0.6*tot:   # clear, stable majority
        track_color[tid]=top
# re-resolve every frame using the voted color (fallback to per-frame color),
# keeping the near-area gate and per-frame uniqueness
for fi in list(per_frame.keys()):
    recs=per_frame[fi]
    proposal=[]   # (priority, area, ri, color)
    for ri,r in enumerate(recs):
        if r["area"]<NEAR_AREA:
            r["id"]="其他"; continue
        voted=track_color.get(r["tid"])
        if voted:                       # priority 0: backed by track vote
            proposal.append((0,r["area"],ri,voted))
        elif r["id"] in idents:         # priority 1: only this frame's color match
            proposal.append((1,r["area"],ri,r["id"]))
        else:
            r["id"]="其他"
    # uniqueness: best (lowest priority, then largest area) wins each color
    proposal.sort(key=lambda p:(p[0],-p[1]))
    taken=set(); usedc=set()
    for pr,ar,ri,col in proposal:
        if ri in taken: continue
        if col in usedc:
            recs[ri]["id"]="其他"; continue
        recs[ri]["id"]=col; taken.add(ri); usedc.add(col)
    for ri,r in enumerate(recs):
        if ri not in taken and r["id"] in idents and r["area"]<NEAR_AREA:
            r["id"]="其他"

# ---------------- per-identity pose metrics + swings ----------------
def best_per_identity(fi, ident):
    cands=[r for r in per_frame.get(fi,[]) if r["id"]==ident]
    if not cands: return None
    return max(cands, key=lambda r:r["area"])

def norm_wrist(rec):
    kp,cf=rec["kp"],rec["cf"]
    if not (kp_ok(kp,cf,LSH) and kp_ok(kp,cf,RSH) and kp_ok(kp,cf,LHIP) and kp_ok(kp,cf,RHIP)): return None
    sh=mid(kp[LSH],kp[RSH]); hip=mid(kp[LHIP],kp[RHIP]); t=np.linalg.norm(sh-hip)
    if t<1e-3: return None
    nl=(kp[LWR]-sh)/t if kp_ok(kp,cf,LWR) else None
    nr=(kp[RWR]-sh)/t if kp_ok(kp,cf,RWR) else None
    ext=[]
    if kp_ok(kp,cf,LWR): ext.append(np.linalg.norm(kp[LWR]-kp[LSH])/t)
    if kp_ok(kp,cf,RWR): ext.append(np.linalg.norm(kp[RWR]-kp[RSH])/t)
    overhead = (kp_ok(kp,cf,LWR) and kp[LWR][1]<sh[1]) or (kp_ok(kp,cf,RWR) and kp[RWR][1]<sh[1])
    stance = np.linalg.norm(kp[LANK]-kp[RANK])/t if (kp_ok(kp,cf,LANK) and kp_ok(kp,cf,RANK)) else np.nan
    return nl,nr,(max(ext) if ext else np.nan),overhead,stance

idents=[id_names[0],id_names[1]]
metrics=defaultdict(list)  # ident -> list of (frame,speed,ext,overhead,stance)
for ident in idents:
    prev=None; prevf=None
    for fi in range(total_frames):
        rec=best_per_identity(fi,ident)
        if rec is None: prev=None; prevf=None; continue
        nw=norm_wrist(rec)
        if nw is None: prev=None; prevf=None; continue
        nl,nr,ext,oh,st=nw
        sp=np.nan
        if prev is not None and prevf==fi-1:
            pl,pr=prev; c=[]
            if nl is not None and pl is not None: c.append(np.linalg.norm(nl-pl))
            if nr is not None and pr is not None: c.append(np.linalg.norm(nr-pr))
            if c: sp=max(c)*FPS
        prev=(nl,nr); prevf=fi
        metrics[ident].append((fi,sp,ext,int(oh),st))

allsp=np.array([m[1] for ident in idents for m in metrics[ident] if not np.isnan(m[1])])
thr=max(float(np.nanmean(allsp)+1.3*np.nanstd(allsp)),4.0) if len(allsp)>10 else 6.0
print(f"swing threshold {thr:.2f}")

swing_events=[]; REFR=7
for ident in idents:
    seq=metrics[ident]; last=-999
    for i in range(1,len(seq)-1):
        sp=seq[i][1]
        if np.isnan(sp): continue
        if sp>=thr and sp>=(seq[i-1][1] if not np.isnan(seq[i-1][1]) else -1) \
           and sp>=(seq[i+1][1] if not np.isnan(seq[i+1][1]) else -1):
            if seq[i][0]-last>=REFR:
                swing_events.append((ident,seq[i][0],round(seq[i][0]/FPS,2),round(sp,2)))
                last=seq[i][0]
# flash windows
flash=defaultdict(set)
for ident,frame,_,_ in swing_events:
    for df in range(5): flash[frame+df].add(ident)

# ---------------- aggregates ----------------
agg=[]
for ident in idents:
    seq=metrics[ident]; n=len(seq); secs=n/FPS
    exts=[m[2] for m in seq if not np.isnan(m[2])]
    sts=[m[4] for m in seq if not np.isnan(m[4])]
    oh=[m[3] for m in seq]
    nsw=sum(1 for e in swing_events if e[0]==ident)
    agg.append({"identity":ident,"frames_present":n,"seconds_present":round(secs,1),
        "swings":nsw,"swings_per_min":round(nsw/secs*60,1) if secs else 0,
        "max_arm_extension":round(max(exts),2) if exts else None,
        "mean_arm_extension":round(float(np.mean(exts)),2) if exts else None,
        "overhead_pct":round(100*float(np.mean(oh)),1) if oh else None,
        "mean_stance_width":round(float(np.mean(sts)),2) if sts else None})
with open(os.path.join(OUT,"color_summary.json"),"w") as f: json.dump(agg,f,indent=2,ensure_ascii=False,default=float)
with open(os.path.join(OUT,"color_summary.csv"),"w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(agg[0].keys())); w.writeheader(); w.writerows(agg)
with open(os.path.join(OUT,"color_swing_events.csv"),"w",newline="") as f:
    w=csv.writer(f); w.writerow(["identity","frame","time_s","intensity"]); w.writerows(swing_events)
print(json.dumps(agg,indent=2,ensure_ascii=False,default=float))

# ---------------- PASS 2: render ----------------
ASCII={"白衣":"WHITE","红衣":"RED","蓝衣":"BLUE","黑衣":"BLACK","黄衣":"YELLOW",
       "绿衣":"GREEN","灰衣":"GRAY","其他":"OTHER"}
def ascii_label(ident): return ASCII.get(ident.rstrip("2"), ident.encode("ascii","ignore").decode() or "P")
# box color = the learned shirt color itself (intuitive); 其他 = gray
ID_BGR={"其他":(150,150,150)}
for c in range(2):
    bgr=cv2.cvtColor(np.uint8([[centers_hsv[c]]]),cv2.COLOR_HSV2BGR)[0,0]
    ID_BGR[id_names[c]]=(int(bgr[0]),int(bgr[1]),int(bgr[2]))
SK=[(5,7),(7,9),(6,8),(8,10),(5,6),(5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16),(0,5),(0,6)]
cap=cv2.VideoCapture(VIDEO)
vw=cv2.VideoWriter(os.path.join(OUT,"annotated_weixin_colorID.mp4"),cv2.VideoWriter_fourcc(*"mp4v"),FPS,(W,Hh))
fi=0
while True:
    ret,frame=cap.read()
    if not ret: break
    for rec in per_frame.get(fi,[]):
        ident=rec["id"]; x1,y1,x2,y2=[int(v) for v in rec["box"]]
        sw = ident in flash.get(fi,set())
        col=ID_BGR.get(ident,(150,150,150))
        cv2.rectangle(frame,(x1,y1),(x2,y2),(0,0,255) if sw else col,3 if sw else 2)
        cv2.putText(frame,ascii_label(ident),(x1,y1-8),cv2.FONT_HERSHEY_SIMPLEX,0.6,col,2)
        kp,cf=rec["kp"],rec["cf"]
        for a,c in SK:
            if cf[a]>=KP_CONF and cf[c]>=KP_CONF:
                cv2.line(frame,(int(kp[a][0]),int(kp[a][1])),(int(kp[c][0]),int(kp[c][1])),(0,140,255),2)
        if sw: cv2.putText(frame,"SWING!",(x1,y2+22),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,0,255),2)
    cv2.putText(frame,f"f{fi}",(10,25),cv2.FONT_HERSHEY_SIMPLEX,0.7,(255,255,255),2)
    vw.write(frame); fi+=1
cap.release(); vw.release()
subprocess.run(["ffmpeg","-loglevel","error","-y",
    "-i",os.path.join(OUT,"annotated_weixin_colorID.mp4"),"-i",VIDEO,
    "-c:v","copy","-map","0:v:0","-map","1:a:0?","-shortest",
    os.path.join(OUT,"annotated_weixin_colorID_audio.mp4")],check=True)
print("DONE")

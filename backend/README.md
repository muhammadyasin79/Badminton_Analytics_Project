# 羽毛球分析后端 (FastAPI)

把现有的姿态分析管线包成一个**异步任务 API**:手机上传 MP4 → 后台跑 YOLO →
返回标注视频 + 指标 + 图表 + 建议。前端见 [`../mobile/`](../mobile/)。

## 本地跑(macOS / Apple Silicon, MPS GPU)

> Python 3.14 还没有 torch wheel,用 **Python 3.12**。

```bash
cd backend
python3.12 -m venv .venv            # 或 ~/.pyenv/versions/3.12.x/bin/python3
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt

# 起服务(0.0.0.0 让同 Wi-Fi 的手机能连)
BAD_DEVICE=mps .venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

查 Mac 局域网 IP(填进手机 App 的「后端地址」):

```bash
ipconfig getifaddr en0     # 例如 192.168.1.23  ->  http://192.168.1.23:8000
```

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET`  | `/` | 健康检查 |
| `POST` | `/jobs` | multipart 上传 mp4/mov → `{ job_id }`,后台开跑 |
| `GET`  | `/jobs/{id}` | `{ status, progress(0-1), stage, error }` |
| `GET`  | `/jobs/{id}/result` | 完成后的 summary JSON(概览/球员/媒体/建议) |
| `GET`  | `/jobs/{id}/video` | 标注视频(支持 HTTP Range,手机可拖动) |
| `GET`  | `/jobs/{id}/chart/{swing_timeline\|feature_dist}` | 图表 PNG |

`status`: `queued → running → done`(或 `error`)。GPU 任务由单线程池串行,避免抢占。

## 命令行直跑(不经 API,便于调试)

```bash
.venv/bin/python pipeline.py /path/to/clip.mp4 -o /tmp/out -d mps
```

## 设计要点
- `pipeline.py` 把 [`../color_id_weixin.py`](../color_id_weixin.py) 和
  [`../pose_analytics_weixin.py`](../pose_analytics_weixin.py) 当**子进程**跑(通过
  `BAD_VIDEO`/`BAD_OUT`/`BAD_DEVICE` 环境变量指向任意视频),**复用已调好的算法**。
- `advice.py` 由指标阈值**自动生成建议**(原 demo 是针对单段视频手写的,换任意视频不适用),
  并始终保留「下压 vs 平抽」免责说明。
- 任务状态在内存里,重启即忘(磁盘产物保留在 `jobs/{id}/out/`)。

## 上云
见 [`DEPLOY.md`](DEPLOY.md)。⚠️ 引入云 GPU 主机属于新的外部服务,**可能需先过公司
External Service Review**。

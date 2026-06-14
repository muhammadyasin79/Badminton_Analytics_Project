# 上云部署说明

> ⚠️ **公司流程提醒**:把分析后端放到云 GPU 主机(AWS / GCP / Azure / Modal /
> Render / RunPod 等)属于引入**新的外部服务**,按公司策略**可能需要先走内部
> "External Service Review"**。请先确认获批,再实际部署。本仓库不内置任何云凭证。

整套后端是**部署无关**的:本地用 `BAD_DEVICE=mps`,云上换成 `cuda`(有 GPU)或
`cpu`(无 GPU,慢),其余代码不变。

## 1. 本地容器自测(无 GPU,验证镜像可跑)

```bash
# 从项目根目录构建(Dockerfile 需要根目录的脚本 + 模型)
docker build -f backend/Dockerfile -t badminton-backend .
docker run --rm -p 8000:8000 badminton-backend
curl localhost:8000/         # {"service":"badminton-analysis",...}
```

CPU 推理较慢,仅用于验证链路;生产用 GPU。

## 2. GPU 镜像(生产)

把 `backend/Dockerfile` 的基础镜像换成带 CUDA 的:

```dockerfile
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
# 安装 python3.12 + pip + ffmpeg libgl1 libglib2.0-0
# pip install 时用 CUDA 版 torch:
#   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
# 其余 requirements 照装
ENV BAD_DEVICE=cuda
```

运行需 `--gpus all`(或云平台的 GPU 实例类型)。

## 3. 部署目标参考

| 平台 | 形态 | 备注 |
|---|---|---|
| Modal / RunPod / Replicate | 按需 GPU,scale-to-zero | 适合"偶尔分析一段",空闲不计费 |
| AWS g5 / GCP L4 | 常驻 GPU VM | 按小时计费,记得用完关机 |
| Render / Fly.io | 容器托管 | GPU 支持有限,确认机型 |

## 4. 上云后端要改的点

1. **前端地址**:`mobile/src/config.js` 的 `DEFAULT_API_BASE` 改成云端域名
   (上云后用 **HTTPS**),App 首页地址栏同步。
2. **收紧明文 HTTP**:`mobile/app.json` 里的 iOS `NSAllowsArbitraryLoads` /
   Android `usesCleartextTraffic` 是为局域网明文调试放开的;走 HTTPS 后可移除。
3. **持久化与清理**:当前任务状态在内存、产物堆在 `jobs/`。生产建议:
   - 任务状态放 Redis / DB;
   - 产物放对象存储(S3/GCS)并设过期清理;
   - 大文件上传走预签名 URL,别全压在一个进程。
4. **鉴权 / 限流**:`/jobs` 目前对所有人开放,公网部署前加 API key 或登录,
   并限制单文件大小与并发,避免被刷爆 GPU。
5. **并发**:GPU 工作目前由单线程池串行(`server.py` 的 `_POOL`)。多 GPU /
   多副本时改成任务队列(Celery / RQ / 云队列)+ 多 worker。

## 5. 健康检查

`GET /` 返回 `{"status":"ok"}`,可直接做云平台的 health check 探针。

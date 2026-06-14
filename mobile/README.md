# 羽毛球分析 · 手机 App(Expo SDK 56 / React Native)

手机上选本地 MP4 → 上传到后端 → 看分析进度 → 看标注视频 + 指标 + 图表 + 建议。

> 工程已对齐 **Expo SDK 56**(react-native 0.85 / react 19),可直接用 **App Store 版
> Expo Go**(只支持最新 SDK)真机扫码运行。`expo-doctor` 21/21 通过。

## 前置:先把后端跑起来

见 [`../backend/README.md`](../backend/README.md)。在你的 Mac 上:

```bash
cd backend
python3 -m uvicorn server:app --host 0.0.0.0 --port 8000
```

记下 Mac 的局域网 IP:

```bash
ipconfig getifaddr en0     # 例如 192.168.1.23
```

## 跑 App(真机 Expo Go,免装 Xcode)

```bash
cd mobile
npm install
npx expo install --fix      # 把依赖对齐到当前 Expo SDK 版本
npx expo start
```

- 手机装 **Expo Go**(App Store / Play Store),与 Mac 连**同一 Wi-Fi**。
- 用 Expo Go 扫终端里的二维码。
- App 首页把「后端地址」改成 `http://<Mac的IP>:8000`(也可直接改 [`src/config.js`](src/config.js) 的默认值)。
- 点「选择视频并分析」,选一段羽毛球 MP4,等进度条走完即可看报告。

## 说明
- 重活全在后端(YOLO 逐帧),手机只负责上传与展示,一段视频约 2~5 分钟。
- 局域网用的是明文 HTTP。用 **Expo Go 开发时 iOS/Android 都默认放行**,无需额外配置。
  若日后打**独立 Android 包**(非 Expo Go)需访问明文 HTTP,再加 `expo-build-properties`
  插件设 `usesCleartextTraffic: true`;上云换 HTTPS 后这些都可去掉。
- 视频选择用 `expo-image-picker`,播放用 `expo-video`,上传进度用 XHR(`src/api.js`)。

## 结构
```
mobile/
├── App.js            状态机:选视频→上传→轮询→结果 + 后端地址输入
├── index.js          入口
├── app.json          Expo 配置(权限/明文 HTTP/插件)
├── src/
│   ├── config.js     后端默认地址 + 轮询间隔
│   ├── api.js        上传(带进度)/ 查询 / 取结果 / 媒体 URL
│   └── Result.js     结果页(视频 + 对比表 + 图表 + 建议)
└── README.md
```

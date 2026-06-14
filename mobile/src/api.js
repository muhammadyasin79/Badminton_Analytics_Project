// Thin client for the badminton analysis backend.

// Upload a picked video file with progress. Uses XHR because fetch in RN does
// not expose upload progress. `onProgress(fraction 0..1)` is called as bytes go.
export function uploadVideo(apiBase, fileUri, filename, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${apiBase}/jobs`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch (err) {
          reject(new Error("返回数据解析失败"));
        }
      } else {
        reject(new Error(`上传失败 (HTTP ${xhr.status}): ${xhr.responseText}`));
      }
    };
    xhr.onerror = () => reject(new Error("网络错误,无法连接后端。请检查地址与同一 Wi-Fi。"));
    xhr.ontimeout = () => reject(new Error("上传超时"));

    const form = new FormData();
    const name = filename || "input.mp4";
    const type = name.toLowerCase().endsWith(".mov") ? "video/quicktime" : "video/mp4";
    // RN FormData file shape
    form.append("file", { uri: fileUri, name, type });
    xhr.send(form);
  });
}

export async function getJob(apiBase, jobId) {
  const r = await fetch(`${apiBase}/jobs/${jobId}`);
  if (!r.ok) throw new Error(`查询任务失败 (HTTP ${r.status})`);
  return r.json();
}

export async function getResult(apiBase, jobId) {
  const r = await fetch(`${apiBase}/jobs/${jobId}/result`);
  if (!r.ok) throw new Error(`获取结果失败 (HTTP ${r.status})`);
  return r.json();
}

export const videoUrl = (apiBase, jobId) => `${apiBase}/jobs/${jobId}/video`;
export const chartUrl = (apiBase, jobId, name) => `${apiBase}/jobs/${jobId}/chart/${name}`;

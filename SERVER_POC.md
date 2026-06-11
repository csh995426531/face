# Server POC Guide

## 1. 服务器镜像

推荐选择：

```text
Pytorch 2.5.0
Python 3.10
Ubuntu 22.04
```

如果 GPU 是 MLU370，不要假设 DeepFace/InsightFace 能直接使用 GPU。第一阶段按 CPU 方案部署。

## 2. 环境检查

```bash
python --version
pip --version
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

`torch.cuda.is_available()` 是 `False` 也可以继续。

## 3. 创建虚拟环境

```bash
cd /path/to/face
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

如果安装 `insightface` 时编译失败，通常是系统缺少编译工具或 Python 头文件。优先换平台内置的 PyTorch/Python 开发镜像，不要在服务器上做系统级改动。

建议把模型缓存放在项目目录，方便查看、迁移和清理：

```bash
export INSIGHTFACE_ROOT="$PWD/.models/insightface"
export DEEPFACE_HOME="$PWD/.models/deepface"
export FACE_DATASET_ROOT="$PWD/datasets"
```

当前代码也会在未设置环境变量时自动使用上面两个项目内目录。

## 4. 启动 Web 页面

```bash
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

然后在平台控制台开放或映射 `7860` 端口，浏览器访问：

```text
http://<server-ip>:7860
```

如果平台给的是带路径前缀的公网入口，例如：

```text
http://222.92.222.140:39090/gb0mx9cg/
```

也可以直接访问这个入口。当前 Web 服务已兼容路径前缀，页面里的 API 请求会走相对路径。

页面支持：

- 上传两张图片
- 从服务器数据集目录选择两张图片，绕过 nginx 上传大小限制
- 切换 `buffalo_l`、`ArcFace`、`Facenet512`、`GhostFaceNet` 等候选配置
- 可选填写自定义阈值
- 查看分数、判断、耗时和原始 JSON
- 显示 Buffalo_L 实际检测到的人脸裁剪预览、bbox 和检测置信度
- 图片本地预览失败时，会自动请求服务端转成标准 JPEG 预览
- 点击比对时会在浏览器端自动压缩图片到 1024px 内，避免平台 nginx 返回 `413 Request Entity Too Large`
- 点击比对会创建后台任务并轮询结果，避免模型首次下载/加载时平台代理返回 `504 Gateway Timeout`
- 批量评估任务和执行结果会保存到 MySQL：

```text
FACE_MYSQL_HOST / FACE_MYSQL_PORT / FACE_MYSQL_USER / FACE_MYSQL_PASSWORD / FACE_MYSQL_DATABASE
```

可用接口查看历史评估任务：

```bash
curl http://127.0.0.1/api/evaluate-jobs
```

## 4.1 Generic Service Task API

新的通用任务入口是 `POST /api/tasks`，用于六类服务：

```text
ocr
face_compare
tamper_detect
liveness
aigc_detect
blacklist
```

请求使用 `multipart/form-data`，固定字段包括 `serviceType`、`requestId`、可选 `sourceProduct`、可选 `payloadJson`、可选 `officialResultJson`。上传文件可以使用任意字段名；服务会保存字段名、顺序、路径、sha256、MIME、大小和原始文件名。幂等键是 `sourceProduct + requestId + serviceType`，同键不同 payload 或文件会返回冲突。

官方生产结果可以内联传入 `officialResultJson`，也可以稍后调用 `POST /api/official-results`：

```json
{
  "sourceProduct": "internal_product_a",
  "requestId": "req-001",
  "serviceType": "face_compare",
  "officialResult": {"samePerson": true},
  "officialStatus": "success",
  "officialElapsedMs": 120,
  "vendorRequestId": "vendor-001"
}
```

如果官方结果先于任务到达，服务会先写入 `pending_official_results`，等对应任务创建后自动绑定。查询任务状态使用 `GET /api/tasks/{taskId}`，返回任务、资产、worker task、官方结果、worker 结果和 comparison 状态。

Worker 使用能力名领取任务：

```text
POST /internal/tasks/lease
POST /internal/tasks/{workerTaskId}/result
```

例如 `face_compare.buffalo_l`、`ocr.baidu_latest`、`liveness.vendor_x`。worker 结果必须由当前持有租约的 worker 提交；租约过期后提交会被拒绝。没有比较适配器的服务会生成 `pending_adapter` comparison 状态；`face_compare` 是当前第一个具体适配路径。旧的 `/api/check` 和 `/internal/model-tasks/*` 仍保留为 face POC 兼容入口。

首次运行某个模型会下载权重并加载模型，等待时间会更长。

## 5. 上传服务器测试图片

建议把测试图片放在：

```text
~/face/datasets/asian-kyc/files
```

本地目录：

```text
/Users/csh/work/abq/doc/face/asian-kyc-photo-dataset-real/files
```

先在服务器创建目录：

```bash
ssh -J admin@222.92.222.140:2202 -p 22 root@10.244.181.149 \
  'mkdir -p /root/face/datasets/asian-kyc/files'
```

从本地上传：

```bash
rsync -avz \
  -e "ssh -J admin@222.92.222.140:2202 -p 22" \
  /Users/csh/work/abq/doc/face/asian-kyc-photo-dataset-real/files/ \
  root@10.244.181.149:/root/face/datasets/asian-kyc/files/
```

启动服务时指定数据目录：

```bash
export FACE_DATASET_ROOT="/root/face/datasets"
uvicorn app.main:app --host 0.0.0.0 --port 80
```

页面会在“图片来源”里默认使用“服务器数据集”，并列出 `FACE_DATASET_ROOT` 下的图片。

如果点击比对后浏览器报“服务没有返回 JSON”或服务端出现下载进度条，先看终端。类似下面这种输出表示正在下载 `buffalo_l` 模型权重，不是程序卡死：

```text
download_path: /root/.insightface/models/buffalo_l
Downloading .../buffalo_l.zip ...
```

这个下载可能会很慢，尤其是从 GitHub 拉取。等下载完成后再次点击比对，后续会直接使用本地缓存。

如果下载速度长期只有几十 KB/s，建议先停止服务，然后手动断点续传 `buffalo_l.zip`：

```bash
mkdir -p .models/insightface/models
curl -L --retry 20 --retry-delay 5 -C - \
  -o .models/insightface/models/buffalo_l.zip \
  https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
```

如果 GitHub 下载得到的文件只有几十字节，说明拿到的是错误响应，不是模型包。可以改用 SourceForge 的 InsightFace 镜像：

```bash
rm -f .models/insightface/models/buffalo_l.zip
curl -L --retry 20 --retry-delay 5 -C - \
  -o .models/insightface/models/buffalo_l.zip \
  "https://sourceforge.net/projects/insightface.mirror/files/v0.7/buffalo_l.zip/download"
ls -lh .models/insightface/models/buffalo_l.zip
```

正常文件大小约 288MB。

下载完成后解压：

```bash
python - <<'PY'
import zipfile
from pathlib import Path

zip_path = Path(".models/insightface/models/buffalo_l.zip")
out_dir = Path(".models/insightface/models/buffalo_l")
out_dir.mkdir(parents=True, exist_ok=True)

with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(out_dir)

print("extracted to", out_dir)
PY
```

然后重新启动：

```bash
export INSIGHTFACE_ROOT="$PWD/.models/insightface"
export DEEPFACE_HOME="$PWD/.models/deepface"
uvicorn app.main:app --host 0.0.0.0 --port 80
```

DeepFace 权重放在：

```text
.models/deepface/.deepface/weights/
```

例如本地下载好的 ArcFace 权重应上传到：

```text
~/face/.models/deepface/.deepface/weights/arcface_weights.h5
```

DeepFace 的 `retinaface` detector 也需要单独权重。若终端出现：

```text
retinaface.h5 will be downloaded from https://github.com/serengil/deepface_models/releases/download/v1.0/retinaface.h5
```

则本地下载 `retinaface.h5` 后上传到：

```text
~/face/.models/deepface/.deepface/weights/retinaface.h5
```

其他 DeepFace 模型同理：先在页面点一次对应模型，终端会打印 `From:` 和 `To:`。把本地下载好的文件上传到 `To:` 对应路径即可，但路径应在：

```text
~/face/.models/deepface/.deepface/weights/
```

InsightFace 权重放在：

```text
~/face/.models/insightface/models/
```

例如：

```text
~/face/.models/insightface/models/buffalo_l/
~/face/.models/insightface/models/buffalo_l.zip
```

Web 页面会显示当前模型缓存状态，也可以命令行查看：

```bash
curl http://127.0.0.1/api/cache
```

## 5. 命令行单次测试

准备两张图片：

```text
samples/a.jpg
samples/b.jpg
```

测试 `buffalo_l`：

```bash
python -m app.core.compare \
  --engine buffalo_l \
  --img-a samples/a.jpg \
  --img-b samples/b.jpg
```

测试 DeepFace ArcFace：

```bash
python -m app.core.compare \
  --engine deepface \
  --model-name ArcFace \
  --detector-backend retinaface \
  --distance-metric cosine \
  --img-a samples/a.jpg \
  --img-b samples/b.jpg
```

首次运行会下载模型权重，速度会慢。正式评估前应先跑一次，确认权重已经下载完成。

## 6. 批量评估

准备 CSV：

```csv
img_a,img_b,label
samples/p1_doc.jpg,samples/p1_selfie.jpg,1
samples/p2_doc.jpg,samples/p3_selfie.jpg,0
```

`label=1` 表示同一人，`label=0` 表示不同人。

运行 `buffalo_l`：

```bash
python -m scripts.evaluate_pairs \
  --pairs pairs.csv \
  --engine buffalo_l \
  --output results-buffalo_l.jsonl
```

运行 DeepFace ArcFace：

```bash
python -m scripts.evaluate_pairs \
  --pairs pairs.csv \
  --engine deepface \
  --model-name ArcFace \
  --detector-backend retinaface \
  --distance-metric cosine \
  --output results-deepface-arcface-retinaface-cosine.jsonl
```

## 7. 第一轮建议测试顺序

```text
1. InsightFace Buffalo_L + cosine
2. DeepFace ArcFace + retinaface + cosine
3. DeepFace ArcFace + retinaface + euclidean_l2
4. DeepFace Facenet512 + retinaface + cosine
5. OpenCV YuNet + SFace + cosine
6. DeepFace GhostFaceNet + retinaface + cosine
```

本 POC 脚本已覆盖前 4 个和第 6 个。OpenCV YuNet + SFace 可作为后续单独补充。

## 8. 评估重点

先看：

```text
不同人误判为同一人的比例 FAR
同一人被拒绝的比例 FRR
无人脸/多人脸失败率
平均耗时
P95 耗时
```

金融场景优先控制 FAR。

## 9. 数据注意事项

不要直接上传大批量真实生产用户照片到第三方 GPU 平台。优先使用内部授权样本或脱敏评估集。测试完成后删除样本和结果文件。

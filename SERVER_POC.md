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
```

## 4. 启动 Web 页面

```bash
uvicorn app:app --host 0.0.0.0 --port 7860
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
- 切换 `buffalo_l`、`ArcFace`、`Facenet512`、`GhostFaceNet` 等候选配置
- 可选填写自定义阈值
- 查看分数、判断、耗时和原始 JSON
- 图片本地预览失败时，会自动请求服务端转成标准 JPEG 预览
- 点击比对时会在浏览器端自动压缩图片到 1024px 内，避免平台 nginx 返回 `413 Request Entity Too Large`

首次运行某个模型会下载权重并加载模型，等待时间会更长。

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
uvicorn app:app --host 0.0.0.0 --port 80
```

## 5. 命令行单次测试

准备两张图片：

```text
samples/a.jpg
samples/b.jpg
```

测试 `buffalo_l`：

```bash
python compare.py \
  --engine buffalo_l \
  --img-a samples/a.jpg \
  --img-b samples/b.jpg
```

测试 DeepFace ArcFace：

```bash
python compare.py \
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
python evaluate_pairs.py \
  --pairs pairs.csv \
  --engine buffalo_l \
  --output results-buffalo_l.jsonl
```

运行 DeepFace ArcFace：

```bash
python evaluate_pairs.py \
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

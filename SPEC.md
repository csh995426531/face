# Face Comparison Replacement Spec

## 目标

替代当前线上 `https://in.bpsdata.com/FaceComparison` 的基础 1:1 人脸比对能力。

本阶段只覆盖：

- 输入两张包含人脸的照片
- 判断是否为同一个人
- 返回相似度/距离、判断结果、模型配置和错误原因

本阶段不覆盖：

- 证件照抽取
- 活体检测
- 反欺诈
- KYC 流程编排
- 人工审核系统

## 核心判断

人脸比对不是单个模型完成，而是一条 pipeline：

```text
image_a/image_b
  -> face detection
  -> face alignment/crop
  -> embedding extraction
  -> distance/similarity calculation
  -> calibrated threshold decision
```

生产上线不能直接使用开源库默认阈值。必须使用印尼市场真实业务样本重新校准阈值。

## 第一轮候选优先级

### P0: 最优先

```text
1. InsightFace Buffalo_L + cosine
```

说明：

- `buffalo_l` 是 InsightFace 的模型包，通常包含检测、对齐和识别能力，不需要额外写成 `retinaface + Buffalo_L`。
- 技术上是服务端 1:1 人脸比对的强候选。
- 最大风险是商用授权：InsightFace 代码是 MIT，但官方预训练模型包通常是 non-commercial research only，生产商用前必须确认授权。

### P1: 强候选

```text
2. DeepFace ArcFace + retinaface + cosine
3. DeepFace ArcFace + retinaface + euclidean_l2
```

说明：

- `ArcFace` 是成熟的人脸 verification 强基线。
- `retinaface` 优先用于检测和对齐，减少裁剪/姿态造成的 embedding 漂移。
- `cosine` 先测，`euclidean_l2` 作为强对照。

### P2: 对照候选

```text
4. DeepFace Facenet512 + retinaface + cosine
```

说明：

- `Facenet512` 不是最新模型，但在一些实际场景中仍可能表现稳定。
- 用于验证它在印尼业务样本上是否优于更新模型。

### P3: 商用授权更清晰的备选

```text
5. OpenCV YuNet + SFace + cosine
```

说明：

- 预期准确率可能弱于 `buffalo_l`，但部署轻、依赖少、授权路径更清楚。
- 必须加入评估，作为低法律风险备选。

### P4: 轻量/成本候选

```text
6. DeepFace GhostFaceNet + retinaface + cosine
```

说明：

- 适合成本敏感、QPS 高、可接受一定准确率折中的场景。
- 不作为金融生产首选，只作为成本备选。

### P5: 历史 baseline

```text
7. DeepFace VGG-Face + retinaface + cosine
```

说明：

- 只用于 baseline 对比。
- 不建议作为生产首选。

## 最小评估集

如果要快速缩小范围，先跑：

```text
1. InsightFace Buffalo_L + cosine
2. DeepFace ArcFace + retinaface + cosine
3. OpenCV YuNet + SFace + cosine
```

## 是否需要训练

第一阶段不训练模型。

优先做：

```text
pretrained model + business sample evaluation + threshold calibration
```

原因：

- 训练人脸识别模型需要大量身份级标注数据。
- 小规模业务数据训练容易过拟合。
- 金融场景下错误训练会增加误判风险。
- 当前需求是替代 1:1 基础比对能力，阈值校准比模型训练更关键。

## 印尼市场样本要求

评估集需要覆盖：

- 正样本：同一人两张不同照片
- 普通负样本：不同人照片
- 困难负样本：相似年龄、性别、地区、长相接近的人
- 证件照 vs 自拍
- 自拍 vs 自拍
- 低光、模糊、侧脸、眼镜、头巾、不同手机

## 评估指标

必须记录：

- FAR: 不同人被判定为同一人的比例
- FRR: 同一人被拒绝的比例
- ROC/AUC
- uncertain rate: 落入不确定区间的比例
- no-face / multi-face error rate
- average latency
- P95 latency
- P99 latency
- memory usage
- CPU/GPU usage

金融场景优先控制 FAR。

## 阈值策略

不要只返回 boolean。生产服务建议返回三段式结果：

```text
high confidence match      -> same_person
gray zone                  -> uncertain / retry / manual review
high confidence non-match  -> different_person
```

示例：

```json
{
  "status": "same_person",
  "same_person": true,
  "similarity": 0.42,
  "model": "insightface/buffalo_l",
  "metric": "cosine",
  "threshold_version": "id-face-v1"
}
```

具体阈值必须由本地样本评估确定，不能直接使用示例值或开源库默认值。

## 推荐服务接口

```http
POST /face/compare
Content-Type: multipart/form-data

image_a=<file>
image_b=<file>
```

返回：

```json
{
  "status": "same_person",
  "same_person": true,
  "score": 0.42,
  "score_type": "cosine_similarity",
  "model": "insightface/buffalo_l",
  "detector": "scrfd",
  "threshold_version": "id-face-v1",
  "elapsed_ms": 187
}
```

错误示例：

```json
{
  "status": "invalid_input",
  "same_person": null,
  "error_code": "MULTIPLE_FACES",
  "message": "expected exactly one face in each image"
}
```

## 上线前检查

- 完成候选模型离线评估
- 选定固定模型、detector、metric
- 完成阈值校准
- 与 BPSData 历史结果做差异对比
- 完成小流量 service validation run
- 确认商用 license
- 固定模型版本和权重来源
- 禁止运行时自动下载模型权重
- 增加日志、监控、限流和超时


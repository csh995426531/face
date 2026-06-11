# Face Recognition Service Evaluation PRD

## 1. 背景

当前内部产品已经在调用外部人脸比对 API：

```http
POST https://api.bpsdata.com/api/check
Content-Type: multipart/form-data

Header:
X-ACCESS-TOKEN=<token>

Form:
firstImage=<file>
secondImage=<file>
```

本项目第一阶段不是直接替换现有生产决策链路，而是作为旁路评估服务。

内部产品在调用现有供应商 API 的同时，也调用本项目 API。本项目 API 接收两张图片后快速落库、入队，由后端多台模型服务器异步执行多种模型配置，并将结果写入数据库。后续通过这些结果和现有供应商结果、人工标签或业务结果进行对比分析，判断是否具备替代现有 API 的能力。

## 2. 目标

### 2.1 第一阶段目标

- 提供兼容内部产品接入习惯的人脸比对接收接口。
- API 请求不阻塞等待模型推理完成。
- 每次请求生成一个比对 job，并为多个模型配置生成独立 task。
- 多台模型服务器从队列消费任务，异步运行对应模型配置。
- 每个模型配置的结果独立落库，便于后续对比分析。
- 支持统计模型准确性、稳定性、耗时、错误类型和灰区分布。

### 2.2 非目标

第一阶段不做：

- 直接替代现有生产 API 的同步判断。
- 参与内部产品主业务决策。
- 同步等待模型结果后再返回调用方。
- 多模型 ensemble 决策。
- 模型服务器跨服务商直连主数据库。
- 模型服务器跨服务商直连 API 云内消息队列。
- 依赖 MLU370 加速作为第一阶段上线前提。
- 活体检测。
- 证件 OCR。
- 反欺诈策略。
- 人工审核系统。
- 训练自有人脸识别模型。

## 3. 核心原则

- 线上调用路径必须轻：接收接口只做鉴权、校验、存储、落库、入队。
- 模型推理必须异步执行。
- 队列消息不传图片二进制，只传图片存储 URI 和任务元数据。
- 每个 worker 进程固定加载一种模型配置。
- 同一台模型服务器可以跑多个 worker 进程，每个进程对应一种模型配置。
- 多模型并行是为了评估，不代表最终生产方案要做 ensemble。
- 最终替代上线前，应收敛到一个主模型配置和一个阈值版本。

## 4. 用户与使用场景

### 4.1 调用方

- 内部产品服务端。
- 内部评估和数据分析人员。
- 模型服务维护人员。

### 4.2 典型流程

```text
内部产品收到人脸比对请求
  -> 调用现有供应商 API，继续用于原有业务判断
  -> 同时调用本项目 API，作为旁路评估
  -> 本项目 API 返回 accepted/job_id
  -> 模型 worker 异步处理多个模型配置
  -> 结果落库
  -> 后续分析供应商结果、模型结果和人工/业务标签差异
```

## 5. 对外 API

### 5.1 生成 Access Token

调用方先使用 `accessKey + secretKey + timestamp` 生成签名，再换取短期 `AccessToken`。业务接口通过 `X-ACCESS-TOKEN` 鉴权。

```http
POST /openapi/auth/ticket/v1/generate-token
Content-Type: application/json
```

请求参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| accessKey | string | 是 | 调用方 accessKey |
| timestamp | string | 是 | 13 位毫秒时间戳，建议与服务端当前时间误差不超过 300 秒 |
| signature | string | 是 | `SHA256(accessKey + secretKey + timestamp)` |
| periodSecond | string | 否 | token 有效期，默认 3600 秒，最小 60 秒，最大 86400 秒 |

签名示例：

```text
accessKey: sampleaccesskey
secretKey: samplesecretkey
timestamp: 1665993522952
combined: sampleaccesskeysamplesecretkey1665993522952
signature: 02209bbeaf0d0a3dd587f6a1ba22f84c98d142e3b545e77db7e4906ca56349f5
```

响应：

```json
{
  "code": "SUCCESS",
  "message": "OK",
  "data": {
    "token": "access_token_xxx",
    "expiredTime": 1665997122952
  },
  "extra": null,
  "transactionId": "txn_20260608_000001",
  "pricingStrategy": "FREE"
}
```

响应码：

| code | message |
| --- | --- |
| SUCCESS | OK |
| PARAMETER_ERROR | Parameter should not be empty |
| PARAMETER_ERROR | Timestamp error |
| PARAMETER_ERROR | Signature error |
| ACCOUNT_DISABLED | Account Disabled |
| CLIENT_ERROR | HTTP 400 - Bad Request |

鉴权规则：

- `secretKey` 只保存在服务端，不在接口响应和日志中输出。
- `timestamp` 与服务端时间误差超过 300 秒时拒绝。
- `periodSecond` 超出范围时拒绝。
- 生成的 AccessToken 只用于调用业务接口，不用于 worker lease、worker result 或运维管理。
- AccessToken 校验后解析出 `sourceProduct`、权限范围和限流配置。

### 5.2 创建人脸比对任务

```http
POST /api/check
Content-Type: multipart/form-data
X-ACCESS-TOKEN: <token>
```

Form 参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| firstImage | file | 是 | 第一张人脸图片 |
| secondImage | file | 是 | 第二张人脸图片 |
| requestId | string | 是 | 调用方请求 ID，用于幂等、追踪和结果关联 |
| sourceProduct | string | 否 | 来源产品或业务线；优先从 token 解析，表单参数仅作为调试或过渡字段 |
| vendorRequestId | string | 否 | 供应商请求 ID，如果调用方可提供 |

建议响应：

```http
HTTP/1.1 202 Accepted
Content-Type: application/json
```

```json
{
  "code": 0,
  "message": "accepted",
  "jobId": "fc_20260608_000001",
  "status": "queued"
}
```

如果调用方暂时无法处理 `202`，可以先返回 `200`，但业务语义仍然是 accepted，不代表模型已经完成判断。

幂等规则：

- 第一阶段要求调用方必须传 `requestId`。
- `sourceProduct` 优先由 `X-ACCESS-TOKEN` 解析得到，不信任外部表单直接声明的来源。
- `sourceProduct + requestId` 是唯一业务幂等键。
- 同一幂等键重复提交时，返回已有 `jobId` 和当前状态，不重复存图、不重复创建 task、不重复 fan-out。
- 如果同一幂等键重复提交但图片内容摘要不同，返回冲突错误，避免错误复用历史结果。

限流和失败规则：

- 按 token 和 `sourceProduct` 配置 QPS、并发上传数和每日任务上限。
- 图片存储失败、数据库写入失败或任务 fan-out 失败时，接口返回失败，不创建半成功 job。
- 如果 job 已创建但 task fan-out 部分失败，必须回滚事务或将 job 标记为 failed 并记录错误，不能返回 accepted。
- API 入口目标是快速失败，不在入口等待 worker 结果。

### 5.3 查询任务状态

第一阶段内部使用即可，不一定对业务调用方开放。

```http
GET /internal/face-recognition/jobs/{jobId}
```

响应示例：

```json
{
  "jobId": "fc_20260608_000001",
  "status": "completed",
  "tasks": [
    {
      "modelConfigId": "buffalo_l_cosine_v1",
      "status": "completed",
      "score": 0.4212,
      "elapsedMs": 184
    },
    {
      "modelConfigId": "arcface_retinaface_cosine_v1",
      "status": "completed",
      "distance": 0.3124,
      "elapsedMs": 712
    }
  ]
}
```

### 5.4 回传供应商结果

如果内部产品能拿到现有供应商 API 的响应，应通过单独接口回传。该接口不影响模型任务执行，只用于后续对比分析。

```http
POST /internal/face-recognition/vendor-results
Content-Type: application/json
X-ACCESS-TOKEN: <token>
```

请求：

```json
{
  "sourceProduct": "internal_product_a",
  "requestId": "biz_req_123",
  "vendorName": "bpsdata",
  "vendorRequestId": "vendor_req_456",
  "vendorStatus": "same_person",
  "vendorScore": 0.91,
  "vendorSamePerson": true,
  "rawResponse": {}
}
```

规则：

- 使用 `sourceProduct + requestId` 关联 `compare_jobs`。
- 第一阶段复用调用方 AccessToken，不单独设计 internal token。
- 供应商结果可以早于或晚于模型结果到达。
- 同一 `job_id + vendor_name + vendor_request_id` 重复回传时必须幂等。
- 如果 job 尚不存在，可以拒绝并要求调用方重试；第一阶段不做 vendor result 暂存队列。

## 6. 系统架构

```text
Internal Product
  |
  | multipart/form-data
  v
API Service
  - auth
  - request validation
  - image storage
  - compare_jobs insert
  - model task fan-out
  - task state management
  - result persistence
  |
  v
Database / Task Queue
  - compare_jobs
  - compare_model_tasks
  - compare_model_results
  |
  | HTTPS lease/result API
  v
Model Workers
  - one process loads one model config
  - lease matching tasks
  - download images by pre-signed URL
  - run face detection/alignment/embedding/similarity
  - submit result to API Service
  |
  v
Analytics
```

模型服务器和 API 服务可能不在同一个服务商。第一阶段默认采用 API 服务持有数据库和任务状态、worker 通过 HTTPS 拉任务和回传结果的方式。不要让跨服务商模型服务器直接连接主数据库。

### 6.1 第一阶段技术栈

第一阶段固定使用以下技术栈：

| 模块 | 技术选择 |
| --- | --- |
| API 服务 | Python 3.10/3.11 + FastAPI |
| HTTP Server | Uvicorn/Gunicorn |
| 数据库 | MySQL 8.0+ / InnoDB |
| 异步任务 | MySQL DB-backed queue + worker polling |
| 图片存储 | 阿里云 OSS |
| Worker | Python worker process |
| 模型 runtime | InsightFace / DeepFace / OpenCV |
| 数据库迁移 | Alembic 或团队现有迁移工具 |
| 部署 | Docker / docker compose |
| 日志 | structured JSON logs |
| 监控 | Prometheus/Grafana 或团队现有监控 |

第一阶段不引入 Kubernetes、Kafka 或复杂微服务拆分。只有当 MySQL polling 成为明确瓶颈，或者团队已有稳定基础设施时，才升级 Redis Streams、RabbitMQ 或 Kafka。

## 7. 图片存储

第一阶段图片存储使用阿里云 OSS。API 服务必须在两张图片均上传 OSS 成功后，才创建 job、创建 task 并允许 worker 拉取任务。

### 7.1 存储规则

- 队列、任务表和 worker 接口只传 OSS object key、OSS URI 或短期签名 URL，不传图片二进制。
- OSS object key 按日期和 job_id 分区，便于生命周期管理。
- 每张图片保存 `image_sha256`、文件大小、MIME 类型、原始文件名和存储 URI。
- 同一个 `sourceProduct + requestId` 重复提交时，必须比较图片摘要；摘要不同则返回冲突错误。
- API 服务不长期依赖本机磁盘；如需临时文件，处理完成后立即删除。

推荐 object key：

```text
face-service-eval/{yyyy}/{mm}/{dd}/{job_id}/first.{ext}
face-service-eval/{yyyy}/{mm}/{dd}/{job_id}/second.{ext}
```

worker 下载图片时使用 OSS 短期签名 URL，默认有效期 10-30 分钟。签名 URL 不写入普通业务日志。

### 7.2 文件限制

第一阶段建议限制：

```text
单张图片最大: 5 MB
支持格式: JPEG, PNG, WEBP
最小边长: 80 px
最大边长: 4096 px
```

只在 API 入口做轻量图片读取和尺寸校验，不在入口做人脸检测。完整人脸检测由模型 worker 执行。

### 7.3 保留周期

默认保留策略：

```text
原始图片: 30 天
模型结果和统计数据: 180 天
错误日志中的敏感字段: 不落或脱敏
```

保留周期必须可配置。需要长期留存的样本应进入单独的脱敏评估集，而不是直接延长线上原图保留时间。

## 8. 异步任务设计

### 8.1 Fan-out 策略

API 服务收到一个 job 后，根据当前启用的模型配置生成多条 task。

第一阶段建议启用：

```text
1. buffalo_l_cosine_v1
2. arcface_retinaface_cosine_v1
3. sface_cosine_v1
```

资源允许后再补充：

```text
4. facenet512_retinaface_cosine_v1
5. ghostfacenet_retinaface_cosine_v1
```

### 8.2 跨服务商任务模式

模型服务器与 API 服务不在同一个服务商时，优先使用 DB-backed queue + worker polling，而不是让模型服务器直接跨云连接 Redis、RabbitMQ、Kafka 或主数据库。

控制面放在 API 服务所在云：

```text
API 服务所在云
  - API Service
  - Database
  - Task state
  - Image storage

模型服务器所在云
  - Model worker
  - HTTPS lease task
  - HTTPS download image
  - HTTPS submit result
```

任务流程：

```text
1. API 接收 firstImage/secondImage
2. API 存储图片
3. API 写 compare_jobs
4. API 写 compare_model_tasks
5. Worker 调用 /internal/model-tasks/lease 拉取任务
6. Worker 使用短期图片 URL 下载图片
7. Worker 执行模型推理
8. Worker 调用 /internal/model-tasks/{taskId}/result 回传结果
9. API 写 compare_model_results 并更新 task/job 状态
```

### 8.3 任务消息

如果后续使用 Redis、RabbitMQ、Kafka 等真实消息队列，队列消息也只包含引用和元数据，不包含图片二进制。

DB-backed queue 模式下，worker lease 接口返回的任务体与队列消息保持同样语义。

```json
{
  "job_id": "fc_20260608_000001",
  "task_id": "ft_20260608_000001_01",
  "model_config_id": "buffalo_l_cosine_v1",
  "first_image_uri": "s3://face-service-eval/2026/06/08/fc_000001_a.jpg",
  "second_image_uri": "s3://face-service-eval/2026/06/08/fc_000001_b.jpg",
  "request_id": "biz_req_123",
  "source_product": "internal_product_a",
  "created_at": "2026-06-08T10:00:00Z"
}
```

### 8.4 Worker lease 接口

```http
POST /internal/model-tasks/lease
X-WORKER-ID: <worker_id>
X-WORKER-TOKEN: <worker_token>
Content-Type: application/json
```

请求：

```json
{
  "modelConfigId": "buffalo_l_cosine_v1",
  "workerId": "model-server-01-buffalo-l",
  "limit": 5
}
```

响应：

```json
{
  "tasks": [
    {
      "taskId": "ft_20260608_000001_01",
      "jobId": "fc_20260608_000001",
      "modelConfigId": "buffalo_l_cosine_v1",
      "firstImageUrl": "https://storage.example.com/presigned/a.jpg",
      "secondImageUrl": "https://storage.example.com/presigned/b.jpg",
      "leaseUntil": "2026-06-08T10:05:00Z"
    }
  ]
}
```

接口行为：

- 只返回和 worker `modelConfigId` 匹配的 queued task。
- 返回任务前将 task 状态改为 running。
- 写入 `worker_id`、`started_at`、`lease_until`。
- `lease_until` 过期且未提交结果的 task 可以重新回到 queued。
- 图片 URL 使用短期预签名 URL，建议有效期 10-30 分钟。

MySQL 实现要求：

- 第一阶段数据库使用 MySQL 8.0+，存储引擎使用 InnoDB。
- lease 领取任务必须在事务内完成。
- 领取任务时使用行级锁，避免多个 worker 领取同一条 task。
- 如果 MySQL 版本支持，优先使用 `SELECT ... FOR UPDATE SKIP LOCKED`。
- 如果不使用 `SKIP LOCKED`，必须用原子 `UPDATE ... WHERE status='queued' ... LIMIT N` 或等价方式先抢占任务，再查询已抢占任务。
- 任务查询索引必须覆盖 `model_config_id`、`status`、`lease_until`、`queued_at`。

推荐领取事务：

```sql
START TRANSACTION;

SELECT task_id
FROM compare_model_tasks
WHERE model_config_id = :model_config_id
  AND status = 'queued'
ORDER BY queued_at
LIMIT :limit
FOR UPDATE SKIP LOCKED;

UPDATE compare_model_tasks
SET status = 'running',
    worker_id = :worker_id,
    started_at = COALESCE(started_at, UTC_TIMESTAMP()),
    lease_until = DATE_ADD(UTC_TIMESTAMP(), INTERVAL :lease_seconds SECOND)
WHERE task_id IN (:task_ids);

COMMIT;
```

租约回收可以由 API 服务定时任务执行：

```sql
UPDATE compare_model_tasks
SET status = 'queued',
    worker_id = NULL,
    lease_until = NULL,
    retry_count = retry_count + 1
WHERE status = 'running'
  AND lease_until < UTC_TIMESTAMP()
  AND retry_count < :max_retries;
```

超过最大重试次数的任务应进入终态：

```sql
UPDATE compare_model_tasks
SET status = 'failed',
    error_code = 'TASK_LEASE_EXPIRED',
    error_message = 'task lease expired after max retries',
    finished_at = UTC_TIMESTAMP()
WHERE status = 'running'
  AND lease_until < UTC_TIMESTAMP()
  AND retry_count >= :max_retries;
```

### 8.5 Worker 结果回传接口

```http
POST /internal/model-tasks/{taskId}/result
X-WORKER-ID: <worker_id>
X-WORKER-TOKEN: <worker_token>
Content-Type: application/json
```

成功结果：

```json
{
  "workerId": "model-server-01-buffalo-l",
  "status": "completed",
  "modelConfigId": "buffalo_l_cosine_v1",
  "score": 0.4212,
  "scoreDirection": "higher_is_more_similar",
  "samePerson": true,
  "threshold": 0.35,
  "thresholdVersion": "id-face-v1",
  "faceCountA": 1,
  "faceCountB": 1,
  "elapsedMs": 184,
  "rawResult": {}
}
```

失败结果：

```json
{
  "workerId": "model-server-01-buffalo-l",
  "status": "failed",
  "modelConfigId": "buffalo_l_cosine_v1",
  "errorCode": "NO_FACE",
  "errorMessage": "no face detected in first image",
  "elapsedMs": 93
}
```

接口行为：

- API 服务统一写 `compare_model_results`。
- API 服务统一更新 `compare_model_tasks` 和 `compare_jobs` 状态。
- worker 不直接写数据库。
- 同一个 `taskId` 的结果提交必须幂等，重复提交已完成结果时返回成功但不重复写入。

### 8.6 重试策略

- 临时错误允许重试，例如对象存储短暂不可用、数据库连接失败。
- 输入错误不重试，例如图片损坏、无脸、多脸、格式不支持。
- 每个 task 需要记录 retry_count 和最后一次错误。
- 重试必须幂等，同一个 task_id 只能产生一份最终结果。
- worker 断线或超时未回传时，由 lease 过期机制释放任务。
- 默认 lease 时长为 5 分钟。
- worker 预计任务无法在 lease 内完成时，应调用续租接口或重新 lease。
- 默认最多重试 3 次，超过后 task 状态改为 failed。
- 重试间隔使用指数退避，避免存储、网络或模型服务短暂异常时集中重试。

续租接口：

```http
POST /internal/model-tasks/{taskId}/renew-lease
X-WORKER-ID: <worker_id>
X-WORKER-TOKEN: <worker_token>
Content-Type: application/json
```

请求：

```json
{
  "workerId": "model-server-01-buffalo-l",
  "leaseSeconds": 300
}
```

续租规则：

- 只有当前持有该 task lease 的 worker 可以续租。
- 已 completed/failed 的 task 不能续租。
- 单次续租最长 10 分钟。

### 8.7 Job 状态聚合

`compare_jobs.status` 由 API 服务根据子任务状态统一维护，worker 不能直接修改 job 状态。

聚合规则：

```text
queued         -> job 已创建，但所有 task 仍未开始
running        -> 至少一个 task running，且仍有未完成 task
completed      -> 所有 task completed
partial_failed -> 至少一个 task failed，且至少一个 task completed
failed         -> 所有 task failed，或 job 创建/fan-out 阶段失败
```

每次 task 完成、失败、租约过期或重试终止后，API 服务都应重新计算 job 状态。

### 8.8 Worker heartbeat

worker 定期上报心跳，用于监控和容量观测。第一阶段 heartbeat 不参与任务分配，任务分配只依赖 lease。

```http
POST /internal/workers/heartbeat
X-WORKER-ID: <worker_id>
X-WORKER-TOKEN: <worker_token>
Content-Type: application/json
```

请求：

```json
{
  "workerId": "model-server-01-buffalo-l",
  "modelConfigId": "buffalo_l_cosine_v1",
  "runtimeVersion": "face-worker-20260608",
  "modelVersion": "buffalo_l_v0.7",
  "status": "healthy",
  "runningTasks": 1,
  "cpuUsage": 0.72,
  "memoryMb": 6144
}
```

规则：

- 心跳间隔建议 15-30 秒。
- 超过 2 分钟没有心跳的 worker 标记为 offline。
- offline 不会立即抢占 running task；task 是否释放仍以 `lease_until` 为准。
- worker 状态用于告警、容量分析和排查，不作为第一阶段调度依赖。

## 9. Worker 部署方式

### 9.1 推荐方式

一个 worker 进程只加载一种模型配置：

```text
worker-buffalo-l-1
  MODEL_CONFIG_ID=buffalo_l_cosine_v1

worker-arcface-1
  MODEL_CONFIG_ID=arcface_retinaface_cosine_v1

worker-sface-1
  MODEL_CONFIG_ID=sface_cosine_v1
```

同一台模型服务器可以运行 2-3 个 worker 进程，但每个进程固定一种模型配置。

这样做的优点：

- 内存和资源消耗可控。
- 单个模型崩溃不会影响其他模型。
- 扩缩容更简单。
- 任务积压可以按模型配置单独观察。
- 模型版本升级和回滚更清楚。

### 9.2 不推荐方式

不建议在一个 worker 进程里同时加载 5 个模型配置并自行调度。

原因：

- 内存占用高且难以定位。
- 任一模型异常可能拖垮整个进程。
- Python 进程内并发对 CPU 推理帮助有限。
- 不利于按模型配置扩缩容。
- 不利于做版本灰度。

### 9.3 跨服务商连接要求

模型服务器跨服务商部署时，worker 只需要访问以下 HTTPS 入口：

```text
POST /internal/model-tasks/lease
POST /internal/model-tasks/{taskId}/result
GET  <pre-signed image url>
POST /internal/workers/heartbeat
```

安全要求：

- 第一阶段 worker 鉴权使用 `X-WORKER-ID + X-WORKER-TOKEN`。
- worker token 必须是至少 32 字节随机值，数据库只保存 hash，不保存明文。
- API 服务校验 worker 是否 enabled、token 是否匹配、来源 IP 是否在 allowlist 内、`modelConfigId` 是否在授权范围内。
- worker/internal 接口不得直接裸露公网；即使跨服务商访问，也应配合安全组、IP allowlist、VPN 或专线。
- 预签名图片 URL 短期有效，过期后必须重新 lease 或刷新。
- 日志中不要输出完整预签名 URL。
- 日志中不要输出 `X-WORKER-TOKEN` 明文。
- 模型服务器不开放数据库账号。
- 模型服务器不直接访问 API 云内 Redis/RabbitMQ/Kafka，除非已有 VPN、专线和访问治理。
- HMAC、timestamp、nonce 防重放和 mTLS 不作为第一阶段要求，进入正式生产替代前再评估是否升级。

性能要求：

- worker 可按 `image_sha256` 做本地图片缓存，避免同一个 job 的多模型任务重复跨云下载同一张图片。
- 记录 `image_download_elapsed_ms`、`model_elapsed_ms`、`result_submit_elapsed_ms`。
- 分析时使用端到端耗时，不只看模型 forward 耗时。

## 10. 模型配置

### 10.1 第一阶段候选

| model_config_id | 说明 | 用途 |
| --- | --- | --- |
| buffalo_l_cosine_v1 | InsightFace Buffalo_L + cosine similarity | 强候选，重点评估 |
| arcface_retinaface_cosine_v1 | DeepFace ArcFace + retinaface + cosine | 强基线 |
| sface_cosine_v1 | OpenCV YuNet + SFace + cosine | 授权风险较低的备选 |
| facenet512_retinaface_cosine_v1 | DeepFace Facenet512 + retinaface + cosine | 对照候选 |
| ghostfacenet_retinaface_cosine_v1 | DeepFace GhostFaceNet + retinaface + cosine | 轻量候选 |

### 10.2 版本固定

每条结果必须记录：

- model_config_id
- model_name
- model_version
- detector
- detector_version
- metric
- threshold_version
- runtime_version
- model_weight_source

上线后禁止运行时自动下载模型权重。模型权重应由部署流程提前准备并校验。

### 10.3 决策输出

评估阶段可以根据当前阈值版本产出模型判断，但不能只保存 boolean。每个模型结果必须同时保存原始分数、阈值版本和三段式决策状态。

推荐状态：

```text
same_person
different_person
uncertain
invalid_input
model_failed
```

规则：

- `same_person` 和 `different_person` 由当前 `threshold_version` 计算得出。
- `uncertain` 表示落在灰区，后续可用于人工复核或阈值校准。
- `invalid_input` 表示无脸、多脸、图片损坏等输入问题。
- `model_failed` 表示模型 runtime 异常、依赖错误或 worker 失败。
- 后续重算阈值时，不覆盖原始分数；可以生成新的分析版本或阈值版本。

## 11. MLU370 加速策略

MLU370 不应默认假设可以直接加速 DeepFace、InsightFace 或 OpenCV SFace。

原因：

- DeepFace 和 InsightFace 常见部署默认依赖 TensorFlow、PyTorch、ONNX Runtime 或 OpenCV CPU/CUDA 路径。
- MLU370 通常需要寒武纪 Neuware、MagicMind 或厂商适配过的推理 runtime。
- 开源模型能否在 MLU370 上加速，取决于模型格式转换、算子支持、前后处理适配和部署镜像。

第一阶段建议：

```text
CPU 跑通异步评估链路
  -> 固定模型和阈值评估方法
  -> 统计 CPU 延迟和吞吐瓶颈
  -> 再单独做 MLU370 可行性验证
```

MLU370 POC 的验收标准：

- 能成功加载转换后的模型权重。
- 单张图片检测、对齐、embedding 输出与 CPU 基线数值差异可接受。
- 1:1 比对分数排序与 CPU 基线基本一致。
- P95/P99 延迟明显优于 CPU 或单位成本更低。
- 部署镜像和驱动依赖可重复交付。

如果 MLU370 只能加速 embedding 模型，检测、图片解码、裁剪、归一化仍可能在 CPU 上执行。评估时必须统计端到端耗时，而不是只统计模型 forward 耗时。

## 12. 数据库设计

第一阶段数据库统一使用 MySQL 8.0+。所有业务表使用 InnoDB，字符集使用 `utf8mb4`。

时间字段建议统一使用 UTC 时间。JSON 类型字段可以使用 MySQL `JSON` 类型；如果后续需要兼容老版本 MySQL，再退化为 `TEXT` 存储 JSON 字符串。

### 12.1 compare_jobs

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| job_id | string | 主任务 ID |
| request_id | string | 调用方请求 ID |
| source_product | string | 来源产品 |
| vendor_request_id | string | 供应商请求 ID |
| first_image_uri | string | 第一张图片存储地址 |
| second_image_uri | string | 第二张图片存储地址 |
| first_image_sha256 | string | 第一张图片内容摘要 |
| second_image_sha256 | string | 第二张图片内容摘要 |
| first_image_size_bytes | integer | 第一张图片大小 |
| second_image_size_bytes | integer | 第二张图片大小 |
| first_image_mime | string | 第一张图片 MIME 类型 |
| second_image_mime | string | 第二张图片 MIME 类型 |
| status | string | queued/running/completed/partial_failed/failed |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### 12.2 compare_model_tasks

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| task_id | string | 模型任务 ID |
| job_id | string | 所属 job |
| model_config_id | string | 模型配置 |
| status | string | queued/running/completed/failed |
| worker_id | string | 当前领取任务的 worker |
| retry_count | integer | 重试次数 |
| queued_at | datetime | 入队时间 |
| started_at | datetime | 开始时间 |
| lease_until | datetime | worker 租约过期时间 |
| finished_at | datetime | 完成时间 |
| error_code | string | 错误码 |
| error_message | string | 错误说明 |

### 12.3 compare_model_results

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| result_id | string | 结果 ID |
| task_id | string | 任务 ID |
| job_id | string | job ID |
| model_config_id | string | 模型配置 |
| score | float | 相似度分数，越大越像时使用 |
| distance | float | 距离，越小越像时使用 |
| score_direction | string | higher_is_more_similar/lower_is_more_similar |
| same_person | boolean | 按当前阈值判断结果 |
| decision_status | string | same_person/different_person/uncertain/invalid_input/model_failed |
| threshold | float | 使用的阈值 |
| threshold_version | string | 阈值版本 |
| face_count_a | integer | 第一张图人脸数量 |
| face_count_b | integer | 第二张图人脸数量 |
| bbox_a_json | json | 第一张图人脸框 |
| bbox_b_json | json | 第二张图人脸框 |
| elapsed_ms | integer | 端到端推理耗时 |
| image_download_elapsed_ms | integer | worker 下载图片耗时 |
| model_elapsed_ms | integer | 模型推理耗时 |
| result_submit_elapsed_ms | integer | 结果回传耗时 |
| raw_result_json | json | 原始模型输出 |
| created_at | datetime | 创建时间 |

### 12.4 vendor_results

如果调用方能提供现有供应商结果，建议单独落表：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| vendor_result_id | string | 供应商结果 ID |
| job_id | string | 对应 job |
| vendor_name | string | 供应商名称 |
| vendor_request_id | string | 供应商请求 ID |
| vendor_status | string | 供应商状态 |
| vendor_score | float | 供应商分数 |
| vendor_same_person | boolean | 供应商判断 |
| raw_response_json | json | 供应商原始响应 |
| created_at | datetime | 创建时间 |

### 12.5 worker_credentials

第一阶段 worker 鉴权使用轻量 token 方案。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| worker_id | string | worker 唯一 ID |
| worker_name | string | 可读名称 |
| token_hash | string | worker token hash，不保存明文 |
| allowed_model_config_ids_json | json | 允许领取的模型配置 |
| ip_allowlist_json | json | 允许访问的 worker 出口 IP |
| status | string | enabled/disabled |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |
| last_seen_at | datetime | 最近心跳时间 |

规则：

- worker token 只在创建或轮换时展示一次。
- token 长度至少 32 字节随机值。
- worker token 不允许调用业务创建任务接口和供应商结果回传接口。
- worker 只能 lease `allowed_model_config_ids_json` 中允许的模型配置。
- 禁用 worker 后，新的 lease、续租、结果回传和 heartbeat 都应拒绝。

### 12.6 推荐索引

`compare_jobs`：

```sql
UNIQUE KEY uk_source_request (source_product, request_id)
KEY idx_status_created_at (status, created_at)
KEY idx_vendor_request_id (vendor_request_id)
```

`compare_model_tasks`：

```sql
UNIQUE KEY uk_job_model (job_id, model_config_id)
KEY idx_lease_pickup (model_config_id, status, lease_until, queued_at)
KEY idx_worker_running (worker_id, status, lease_until)
KEY idx_job_status (job_id, status)
```

`compare_model_results`：

```sql
UNIQUE KEY uk_task_id (task_id)
KEY idx_job_model (job_id, model_config_id)
KEY idx_model_created_at (model_config_id, created_at)
```

`vendor_results`：

```sql
KEY idx_job_vendor (job_id, vendor_name)
KEY idx_vendor_request_id (vendor_request_id)
```

`worker_credentials`：

```sql
PRIMARY KEY (worker_id)
KEY idx_status_last_seen (status, last_seen_at)
```

## 13. 错误码

| error_code | 说明 | 是否重试 |
| --- | --- | --- |
| INVALID_TOKEN | token 无效 | 否 |
| WORKER_AUTH_MISSING | worker 鉴权头缺失 | 否 |
| WORKER_AUTH_FAILED | worker token 校验失败 | 否 |
| WORKER_DISABLED | worker 已禁用 | 否 |
| WORKER_IP_DENIED | worker 来源 IP 不允许 | 否 |
| WORKER_MODEL_FORBIDDEN | worker 无权领取该模型配置 | 否 |
| IMAGE_TOO_LARGE | 图片过大 | 否 |
| UNSUPPORTED_IMAGE_FORMAT | 图片格式不支持 | 否 |
| IMAGE_READ_FAILED | 图片无法读取 | 否 |
| NO_FACE | 未检测到人脸 | 否 |
| MULTIPLE_FACES | 检测到多张人脸 | 否 |
| STORAGE_FAILED | 图片存储失败 | 是 |
| TASK_FANOUT_FAILED | 创建模型子任务失败 | 是 |
| TASK_LEASE_EXPIRED | worker 租约过期 | 是 |
| RESULT_SUBMIT_FAILED | worker 结果回传失败 | 是 |
| MODEL_RUNTIME_ERROR | 模型运行异常 | 视情况 |
| DB_WRITE_FAILED | 数据库写入失败 | 是 |

## 14. 分析指标

第一阶段必须支持以下分析：

- 每个模型配置的成功率。
- no-face / multi-face / image-read-failed 比例。
- 平均耗时、P95、P99。
- 模型之间判断一致率。
- 模型与现有供应商判断一致率。
- 如果有人工作业标签，则计算 FAR、FRR、ROC/AUC。
- 灰区样本占比。
- 按图片来源、业务线、时间、设备渠道切片。

金融场景优先控制 FAR，即不同人被判定为同一人的比例。

### 14.1 M3 最小分析报告

M3 阶段必须输出固定格式的模型对比报告，不能只提供原始表。

报告至少包含：

- 总请求数、成功任务数、失败任务数。
- 每个模型配置的成功率、失败率、no-face 率、multi-face 率。
- 每个模型配置的 P50/P95/P99 端到端耗时。
- 每个模型配置与供应商结果的一致率。
- 多模型之间的一致率矩阵。
- 灰区样本占比。
- 按 `sourceProduct`、日期、图片类型切片的核心指标。
- 可导出的样本明细，包括 job_id、request_id、模型分数、供应商结果和错误码。

如果没有人工标签，报告只能说明模型与供应商的一致性，不能宣称真实准确率。只有接入人工标签或可靠业务标签后，才计算 FAR、FRR、ROC/AUC。

## 15. 安全与合规

- 图片属于敏感个人数据，必须限制访问权限。
- 图片存储 URI 不应暴露给无关系统。
- API token 不能写入普通业务日志。
- 日志中不要输出图片二进制、base64 或完整公网临时访问地址。
- 图片保留周期需要可配置。
- 分析导出需要脱敏。
- 生产商用前必须确认所用模型和预训练权重的 license。

### 15.1 鉴权分层

第一阶段实现两类鉴权：调用方 AccessToken 和 worker token。internal token 暂不单独设计。

调用方鉴权规则：

- 调用方使用 `accessKey + secretKey + timestamp` 生成 SHA256 签名并换取 AccessToken。
- AccessToken 通过 `X-ACCESS-TOKEN` 调用业务接口。
- `secretKey` 只保存服务端，不写日志、不返回给调用方。
- AccessToken 只存 hash 或可验证摘要，不在日志中记录明文。
- AccessToken 校验后解析出 `sourceProduct`、权限范围、限流配置和过期时间。
- AccessToken 必须支持禁用、轮换和过期。

worker 鉴权规则：

- worker 调用 `/internal/model-tasks/*` 和 `/internal/workers/heartbeat` 时必须传 `X-WORKER-ID` 和 `X-WORKER-TOKEN`。
- `X-WORKER-TOKEN` 至少 32 字节随机值。
- 数据库只保存 worker token hash，不保存明文。
- 服务端校验 worker 状态、token hash、IP allowlist 和模型配置权限。
- 日志只记录 `worker_id`，不记录 `X-WORKER-TOKEN`。
- worker token 支持禁用和轮换。

internal 接口规则：

- `/internal/face-recognition/vendor-results` 第一阶段复用调用方 AccessToken。
- 正式生产替代前，再评估是否补充 internal token、HMAC、nonce 防重放或 mTLS。

## 16. 运维监控

必须监控：

- API 请求量、成功率、错误率。
- API 入队耗时。
- 队列积压长度。
- 各模型 task 成功率、失败率、重试次数。
- 各模型 P50/P95/P99 耗时。
- worker 进程存活状态。
- worker lease 成功率、租约过期数、结果回传失败数。
- worker 跨云图片下载耗时。
- CPU、内存、磁盘、网络使用率。
- 阿里云 OSS 读写失败率。
- 数据库写入失败率。

## 17. 里程碑

### M1: 接收链路

- 实现 `/api/check`。
- 完成 AccessToken 生成和 `X-ACCESS-TOKEN` 鉴权。
- 完成图片校验和存储。
- 完成 compare_jobs 和 compare_model_tasks 落库。
- 完成任务 fan-out。
- 完成 worker token 鉴权。
- 完成 worker lease 接口。

### M2: Worker 链路

- 实现按 model_config_id 拉取任务。
- 每个 worker 固定加载一种模型配置。
- 完成预签名图片 URL 下载。
- 完成结果回传接口。
- 完成 API 服务统一落库。
- 完成失败重试和错误码记录。

### M3: 多模型评估

- 跑通 3 个核心模型配置。
- 建立结果查询和导出能力。
- 输出第一版模型对比报告。

### M4: 替代可行性判断

- 接入现有供应商结果或人工标签。
- 完成 FAR、FRR、灰区和延迟分析。
- 明确候选主模型和阈值版本。
- 决定是否进入小流量同步替代试点。

### 阶段验收标准

M1 验收：

- 同一 `sourceProduct + requestId` 重复提交返回同一个 `jobId`。
- 图片存储失败时不会创建可执行 task。
- 成功请求可在 MySQL 中看到 1 条 job 和 N 条 model task。
- API 返回耗时 P95 在 800 ms 以内，不等待模型结果。

M2 验收：

- 多个同模型 worker 并发 lease 时，不会领取同一个 task。
- 未携带或携带错误 `X-WORKER-TOKEN` 的 worker 不能 lease task。
- worker 不能 lease 未授权的 `modelConfigId`。
- worker 断线后，task 在 `lease_until` 过期后可重新领取。
- completed task 重复回传结果不会重复写入。
- 失败 task 按错误类型正确重试或终止。

M3 验收：

- 3 个核心模型配置均可稳定产出结果。
- 每个模型配置都有成功率、错误率、P95/P99 耗时。
- 可以导出样本明细用于人工核查。
- 可以生成固定格式的模型对比报告。

M4 验收：

- 至少完成一版模型与供应商结果对比。
- 如果已有人工标签，完成 FAR、FRR、灰区和阈值建议。
- 明确主候选模型、阈值版本、license 风险和上线阻塞项。

## 18. 开放问题

- 内部产品是否能稳定传 `requestId`；如果短期不能传，需要 API 网关或接入层生成并回传。
- 现有供应商原始结果是否能通过 `/internal/face-recognition/vendor-results` 回传。
- 后续是否需要从 MySQL DB-backed queue 升级 Redis、RabbitMQ、Kafka 或现有内部队列。
- 图片和结果保留周期是否需要按业务线差异化配置。
- MLU370 是否有可用 Neuware/MagicMind 镜像和模型转换工具链。

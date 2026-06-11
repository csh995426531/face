# Deployment

This project has two runtime roles:

- `api`: FastAPI app for Web POC, OpenAPI-compatible ingestion, task lease/result APIs.
- `worker`: one model worker process. Start one or more workers, each with one `FACE_WORKER_MODEL_CONFIG_ID`.

MySQL is external. The project does not start or manage MySQL.

## Schema Migration

Run an explicit SQL migration before starting a new API version.

First deployment:

```bash
python -m scripts.migrate migrations/0001_init_schema.sql
```

For later iterations, add a new SQL file under `migrations/` and run that file explicitly before starting the new API version.

After the schema migration, insert the required `api_clients` rows, then start the API.

## API

```bash
export FACE_MYSQL_HOST="mysql.example.internal"
export FACE_MYSQL_PORT="3306"
export FACE_MYSQL_USER="face"
export FACE_MYSQL_PASSWORD="change-me"
export FACE_MYSQL_DATABASE="face_service_eval"
export FACE_SERVICE_MODEL_CONFIG_IDS="buffalo_l,arcface_retinaface_cosine,arcface_retinaface_euclidean_l2,facenet512_retinaface_cosine,ghostfacenet_retinaface_cosine"
export FACE_WORKER_CREDENTIALS_JSON='[
  {"worker_id":"worker-buffalo-l","worker_token":"change-me-buffalo","allowed_model_config_ids":["buffalo_l"],"allowed_capabilities":["face_compare.buffalo_l"]},
  {"worker_id":"worker-arcface-cosine","worker_token":"change-me-arcface-cosine","allowed_model_config_ids":["arcface_retinaface_cosine"],"allowed_capabilities":["face_compare.arcface_retinaface_cosine"]},
  {"worker_id":"worker-arcface-euclidean-l2","worker_token":"change-me-arcface-euclidean-l2","allowed_model_config_ids":["arcface_retinaface_euclidean_l2"],"allowed_capabilities":["face_compare.arcface_retinaface_euclidean_l2"]},
  {"worker_id":"worker-facenet512","worker_token":"change-me-facenet512","allowed_model_config_ids":["facenet512_retinaface_cosine"],"allowed_capabilities":["face_compare.facenet512_retinaface_cosine"]},
  {"worker_id":"worker-ghostfacenet","worker_token":"change-me-ghostfacenet","allowed_model_config_ids":["ghostfacenet_retinaface_cosine"],"allowed_capabilities":["face_compare.ghostfacenet_retinaface_cosine"]}
]'

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Worker

Run one process per model config:

```bash
export FACE_API_BASE_URL="http://127.0.0.1:8000"
export FACE_WORKER_ID="worker-buffalo-l"
export FACE_WORKER_TOKEN="change-me-buffalo"
export FACE_WORKER_MODEL_CONFIG_ID="buffalo_l"
export FACE_WORKER_CAPABILITY="face_compare.buffalo_l"

python -m worker.main
```

Start another worker by changing `FACE_WORKER_ID`, `FACE_WORKER_TOKEN`, `FACE_WORKER_MODEL_CONFIG_ID`, and `FACE_WORKER_CAPABILITY`.

## Docker Compose

`docker-compose.yml` starts one API container and one worker per configured model. It intentionally does not include MySQL.

```bash
cp .env.example .env
# edit .env and point FACE_MYSQL_* to the existing MySQL instance

export FACE_MYSQL_HOST="mysql.example.internal"
export FACE_MYSQL_USER="face"
export FACE_MYSQL_PASSWORD="change-me"
export FACE_MYSQL_DATABASE="face_service_eval"

docker compose up -d --build
```

Shared volumes:

- `.data`: uploaded service images and task image files.
- `.models`: model weights/cache.
- `datasets`: optional Web POC server-side dataset.

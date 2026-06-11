CREATE TABLE IF NOT EXISTS api_clients (
    api_id VARCHAR(128) PRIMARY KEY,
    access_key VARCHAR(128) NOT NULL UNIQUE,
    secret_key VARCHAR(255) NOT NULL,
    remark VARCHAR(255),
    status VARCHAR(32) NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS access_tokens (
    token_hash VARCHAR(128) PRIMARY KEY,
    access_key VARCHAR(128) NOT NULL,
    api_id VARCHAR(128) NOT NULL,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS compare_jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    job_type VARCHAR(32) NOT NULL DEFAULT 'api_check',
    request_id VARCHAR(191) NOT NULL,
    api_id VARCHAR(128) NOT NULL,
    vendor_request_id VARCHAR(191),
    first_image_uri VARCHAR(1024) NOT NULL,
    second_image_uri VARCHAR(1024) NOT NULL,
    first_image_sha256 CHAR(64) NOT NULL,
    second_image_sha256 CHAR(64) NOT NULL,
    first_image_size_bytes INTEGER NOT NULL,
    second_image_size_bytes INTEGER NOT NULL,
    first_image_mime VARCHAR(64) NOT NULL,
    second_image_mime VARCHAR(64) NOT NULL,
    first_original_filename VARCHAR(512),
    second_original_filename VARCHAR(512),
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(64),
    error_message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE KEY uk_api_request (api_id, request_id),
    KEY idx_job_type_status (job_type, status, created_at),
    KEY idx_status_created_at (status, created_at),
    KEY idx_vendor_request_id (vendor_request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS compare_model_tasks (
    task_id VARCHAR(96) PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL,
    model_config_id VARCHAR(128) NOT NULL,
    threshold VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    worker_id VARCHAR(128),
    retry_count INTEGER NOT NULL DEFAULT 0,
    queued_at REAL NOT NULL,
    started_at REAL,
    lease_until REAL,
    finished_at REAL,
    error_code VARCHAR(64),
    error_message TEXT,
    UNIQUE KEY uk_job_model (job_id, model_config_id),
    KEY idx_lease_pickup (model_config_id, status, lease_until, queued_at),
    KEY idx_worker_running (worker_id, status, lease_until),
    KEY idx_job_status (job_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS compare_model_results (
    result_id VARCHAR(96) PRIMARY KEY,
    task_id VARCHAR(96) NOT NULL UNIQUE,
    job_id VARCHAR(64) NOT NULL,
    model_config_id VARCHAR(128) NOT NULL,
    score REAL,
    distance REAL,
    score_direction VARCHAR(32),
    same_person INTEGER,
    decision_status VARCHAR(32) NOT NULL,
    threshold REAL,
    threshold_version VARCHAR(128),
    face_count_a INTEGER,
    face_count_b INTEGER,
    bbox_a_json JSON,
    bbox_b_json JSON,
    elapsed_ms INTEGER,
    image_download_elapsed_ms INTEGER,
    model_elapsed_ms INTEGER,
    result_submit_elapsed_ms INTEGER,
    raw_result_json JSON,
    created_at REAL NOT NULL,
    KEY idx_job_model (job_id, model_config_id),
    KEY idx_model_created_at (model_config_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vendor_results (
    vendor_result_id VARCHAR(96) PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL,
    vendor_name VARCHAR(128) NOT NULL,
    vendor_request_id VARCHAR(191) NOT NULL,
    vendor_status VARCHAR(64),
    vendor_score REAL,
    vendor_same_person INTEGER,
    raw_response_json JSON,
    created_at REAL NOT NULL,
    UNIQUE KEY uk_job_vendor_request (job_id, vendor_name, vendor_request_id),
    KEY idx_job_vendor (job_id, vendor_name),
    KEY idx_vendor_request_id (vendor_request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS worker_credentials (
    worker_id VARCHAR(128) PRIMARY KEY,
    worker_name VARCHAR(256) NOT NULL,
    token_hash VARCHAR(128) NOT NULL,
    allowed_model_config_ids_json JSON NOT NULL,
    allowed_capabilities_json JSON NOT NULL,
    ip_allowlist_json JSON NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_seen_at REAL,
    KEY idx_status_last_seen (status, last_seen_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id VARCHAR(128) PRIMARY KEY,
    model_config_id VARCHAR(128) NOT NULL,
    runtime_version VARCHAR(128),
    model_version VARCHAR(128),
    status VARCHAR(32) NOT NULL,
    running_tasks INTEGER,
    cpu_usage REAL,
    memory_mb REAL,
    payload_json JSON NOT NULL,
    updated_at REAL NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS service_jobs (
    task_id VARCHAR(96) PRIMARY KEY,
    service_type VARCHAR(64) NOT NULL,
    api_id VARCHAR(128) NOT NULL,
    request_id VARCHAR(191) NOT NULL,
    status VARCHAR(32) NOT NULL,
    raw_payload_json LONGTEXT,
    payload_hash CHAR(64) NOT NULL,
    assets_hash CHAR(64) NOT NULL,
    metadata_json JSON,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE KEY uk_service_request (api_id, request_id, service_type),
    KEY idx_service_status (service_type, status, created_at),
    KEY idx_api_request (api_id, request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS service_assets (
    asset_id VARCHAR(96) PRIMARY KEY,
    task_id VARCHAR(96) NOT NULL,
    field_name VARCHAR(191) NOT NULL,
    position INTEGER NOT NULL,
    uri VARCHAR(1024) NOT NULL,
    sha256 CHAR(64) NOT NULL,
    mime VARCHAR(128) NOT NULL,
    size_bytes INTEGER NOT NULL,
    original_filename VARCHAR(512),
    created_at REAL NOT NULL,
    KEY idx_task_field (task_id, field_name, position),
    KEY idx_asset_sha (sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS service_worker_tasks (
    worker_task_id VARCHAR(96) PRIMARY KEY,
    task_id VARCHAR(96) NOT NULL,
    capability VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    worker_id VARCHAR(128),
    retry_count INTEGER NOT NULL DEFAULT 0,
    queued_at REAL NOT NULL,
    started_at REAL,
    lease_until REAL,
    finished_at REAL,
    error_code VARCHAR(64),
    error_message TEXT,
    UNIQUE KEY uk_task_capability (task_id, capability),
    KEY idx_capability_pickup (capability, status, lease_until, queued_at),
    KEY idx_service_worker_running (worker_id, status, lease_until),
    KEY idx_task_status (task_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS official_results (
    official_result_id VARCHAR(96) PRIMARY KEY,
    task_id VARCHAR(96) NOT NULL,
    api_id VARCHAR(128) NOT NULL,
    request_id VARCHAR(191) NOT NULL,
    service_type VARCHAR(64) NOT NULL,
    official_status VARCHAR(64),
    official_elapsed_ms INTEGER,
    vendor_request_id VARCHAR(191),
    raw_result_json LONGTEXT NOT NULL,
    result_hash CHAR(64) NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE KEY uk_official_service_request (api_id, request_id, service_type),
    KEY idx_official_task (task_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS worker_results (
    worker_result_id VARCHAR(96) PRIMARY KEY,
    worker_task_id VARCHAR(96) NOT NULL UNIQUE,
    task_id VARCHAR(96) NOT NULL,
    capability VARCHAR(128) NOT NULL,
    worker_id VARCHAR(128) NOT NULL,
    result_status VARCHAR(32) NOT NULL,
    elapsed_ms INTEGER,
    raw_result_json LONGTEXT NOT NULL,
    normalized_result_json LONGTEXT,
    created_at REAL NOT NULL,
    KEY idx_worker_result_task (task_id, created_at),
    KEY idx_worker_result_capability (capability, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS comparison_results (
    comparison_id VARCHAR(96) PRIMARY KEY,
    task_id VARCHAR(96) NOT NULL,
    service_type VARCHAR(64) NOT NULL,
    capability VARCHAR(128),
    official_result_id VARCHAR(96),
    worker_result_id VARCHAR(96),
    compare_status VARCHAR(32) NOT NULL,
    diff_json LONGTEXT,
    created_at REAL NOT NULL,
    KEY idx_comparison_task (task_id, created_at),
    KEY idx_compare_status (compare_status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pending_official_results (
    pending_id VARCHAR(96) PRIMARY KEY,
    api_id VARCHAR(128) NOT NULL,
    request_id VARCHAR(191) NOT NULL,
    service_type VARCHAR(64) NOT NULL,
    official_status VARCHAR(64),
    official_elapsed_ms INTEGER,
    vendor_request_id VARCHAR(191),
    raw_result_json LONGTEXT NOT NULL,
    result_hash CHAR(64) NOT NULL,
    created_at REAL NOT NULL,
    attached_task_id VARCHAR(96),
    attached_at REAL,
    UNIQUE KEY uk_pending_service_request (api_id, request_id, service_type),
    KEY idx_pending_attached (attached_task_id, attached_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS evaluation_jobs (
    job_id VARCHAR(96) PRIMARY KEY,
    status VARCHAR(32) NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    positive_limit_per_group INTEGER NOT NULL,
    negative_limit_per_group INTEGER NOT NULL,
    pairs INTEGER,
    positive_pairs INTEGER,
    negative_pairs INTEGER,
    payload_json JSON NOT NULL,
    KEY idx_evaluation_jobs_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS evaluation_model_results (
    job_id VARCHAR(96) NOT NULL,
    config_id VARCHAR(128) NOT NULL,
    summary_json JSON NOT NULL,
    details_json JSON NOT NULL,
    PRIMARY KEY (job_id, config_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

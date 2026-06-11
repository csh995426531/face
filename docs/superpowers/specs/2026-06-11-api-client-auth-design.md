# API Client Auth Design

**Date:** 2026-06-11

## Goal

Replace the single env-configured API caller with a database-backed caller registry so multiple callers can be managed over time without using `FACE_API_SOURCE_PRODUCT`.

## Scope

- Add a persistent `api_clients` table for caller management.
- Replace env-based API caller lookup with database lookup by `access_key`.
- Bind issued access tokens to `api_id`.
- Replace `source_product` ownership in API-authenticated records with `api_id`.
- Keep worker auth unchanged.

## Data Flow

1. Caller sends `accessKey`, `timestamp`, `signature`, and `periodSecond` to `/openapi/auth/ticket/v1/generate-token`.
2. API loads the caller row from `api_clients` by `access_key`.
3. API verifies the signature using the stored `secret_key`.
4. API stores the generated access token in `access_tokens` with `api_id`.
5. Authenticated task and result routes resolve `api_id` from the access token and persist it into job/result records.

## Schema Changes

### New Table

- `api_clients`
  - `api_id` primary key
  - `access_key` unique
  - `secret_key`
  - `remark`
  - `status`
  - `created_at`
  - `updated_at`

### Updated Tables

- `access_tokens`: replace `source_product` with `api_id`
- `compare_jobs`: replace `source_product` with `api_id`; unique key becomes `(api_id, request_id)`
- `service_jobs`: replace `source_product` with `api_id`; unique key becomes `(api_id, request_id, service_type)`
- `official_results`: replace `source_product` with `api_id`; unique key becomes `(api_id, request_id, service_type)`
- `pending_official_results`: replace `source_product` with `api_id`; unique key becomes `(api_id, request_id, service_type)`

## Route and Service Contracts

- `sourceProduct` is no longer read from request payloads or forms on authenticated API routes.
- Token generation succeeds only for enabled `api_clients`.
- API-authenticated create/read/write flows use token-derived `api_id` as the caller boundary.
- Response payloads that currently expose `sourceProduct` should expose `apiId` instead for API-authenticated resources.

## Validation

- Missing or unknown `access_key` returns the existing account-disabled path.
- Signature validation format stays unchanged except that the secret is loaded from `api_clients`.
- Authenticated task creation still requires `requestId` and `serviceType`.
- Idempotency conflicts stay scoped per caller via `api_id`.

## Testing

- Add a repository/service-level path proving token generation reads caller credentials from the database.
- Update route and contract tests to assert `api_clients` bootstrapping and `api_id`-scoped uniqueness.
- Remove env-variable assumptions for API caller config from tests.

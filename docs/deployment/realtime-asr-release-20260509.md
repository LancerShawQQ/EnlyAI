# Realtime ASR Hardening Release 20260509

## Scope

This release closes the remaining launch-blocking work for the realtime ASR rollout associated with deployment `20260509-124240-realtime-asr`.

It covers three areas together:

1. Multi-instance safe realtime ASR session state.
2. Final stabilization of high-fanout Playwright browser regressions.
3. Release-facing operational guidance for deployment and rollback.

## What Changed

### Realtime ASR session ownership, Redis coordination, and shared registry

- Added a new SQLite table `realtime_transcription_sessions` to persist realtime ASR session metadata.
- Added `lib/server/runtime-instance.ts` so each runtime instance has a stable owner ID.
- Reworked `lib/audio/funasr-realtime-session-store.ts` to use:
  - in-memory live websocket handles on the owning instance
  - SQLite-backed shared metadata and lifecycle state
  - Redis-backed owner heartbeat and cross-instance command dispatch
  - authenticated `ownerUserId` binding for every realtime session
  - serialized append/finish operations per session
  - explicit owner, unavailable, not-found, and invalid-state errors
- Added `app/api/transcription/realtime/route.ts` to expose `start`, `append`, `finish`, and `cancel` actions.
- Added `lib/audio/funasr-realtime-metrics.ts` and `GET /api/admin?type=realtime` for operational monitoring.
- The admin realtime snapshot exposes instance-local status code counters plus shared SQLite session summary and shared Redis instance heartbeats.
- Added guardrails to the realtime route and store:
  - authenticated access only
  - per-user active session cap
  - per-chunk request size cap
  - per-session cumulative audio size cap

### Voice race-condition hardening

- Hardened manual voice input in roundtable mode against stale transcript delivery after cancel, dismiss, or provider switching.
- Added realtime interim transcription handling for FunASR/Qwen streaming ASR in `use-audio-recorder`.
- Preserved idempotent `finish` behavior by retaining final transcript text for a short terminal window.

### Browser regression stabilization

- Updated Playwright specs to reflect the current landing page and authenticated studio flow.
- Replaced unstable assertions tied to provider display names or `networkidle` waits with stable surface assertions.
- Added stable `data-testid="studio-import-classroom"` hooks for workspace import entrypoints.

## Deployment Requirements

### Launch topology

This release supports multi-instance application deployment only when all instances share the same Redis coordinator.

Reason:

- The websocket handle for FunASR realtime transcription remains process-local on the owner instance.
- SQLite stores shared metadata and owner truth.
- Redis distributes `append`, `finish`, and `cancel` requests to the owner instance and returns the result.
- If the owner heartbeat disappears, the API returns `503` instead of routing blindly.

### Relevant environment variables

- `REALTIME_INSTANCE_ID`
  - Optional explicit runtime owner ID.
  - If unset, the app derives one from hostname, pid, and a random suffix.
- `REALTIME_SESSION_TTL_MS`
  - Optional active-session TTL.
  - Default: 2 minutes.
- `REALTIME_SESSION_TERMINAL_RETENTION_MS`
  - Optional retention for `finished`, `cancelled`, `expired`, and `failed` session metadata.
  - Default: 5 minutes.
- `REALTIME_REDIS_URL`
  - Required for multi-instance realtime ASR.
- `REALTIME_REDIS_HEARTBEAT_INTERVAL_MS`
  - Default: 10 seconds.
- `REALTIME_REDIS_HEARTBEAT_TTL_SECONDS`
  - Default: 30 seconds.
- `REALTIME_REDIS_OPERATION_TIMEOUT_SECONDS`
  - Default: 15 seconds.

### API behavior in production

`/api/transcription/realtime` now returns more specific status codes:

- `401`: caller is not authenticated.
- `413`: chunk or session payload exceeds allowed limits.
- `429`: caller already has too many active realtime ASR sessions.
- `404`: session missing or already terminal and unavailable.
- `409`: wrong owner instance or invalid lifecycle state.
- `503`: owner metadata exists but the live handle is unavailable on that instance.

These codes are intentional and should not be flattened by ingress or proxy layers.

## Verification Completed

### Vitest

Targeted realtime/voice regression suite passed:

- `tests/audio/funasr-realtime-session-registry.test.ts`
- `tests/audio/funasr-realtime-session-store.test.ts`
- `tests/server/realtime-transcription-route.test.ts`
- `tests/audio/use-audio-recorder-interim.test.tsx`
- `tests/audio/use-audio-recorder-session.test.tsx`

Result: 5 files, 14 tests passed.

### Playwright

Targeted browser regression suite passed:

- `e2e/tests/home-footer-quick-start.spec.ts`
- `e2e/tests/generation-flow.spec.ts`
- `e2e/tests/home-to-generation.spec.ts`

Result: 18 tests passed.

## Operational Notes

### Rollback

Application rollback is safe as long as the shared SQLite database is preserved.

The new registry table is additive and does not block rollback to an earlier application build.

### Monitoring focus

After release, watch for these signals:

1. Increased `409` responses on `/api/transcription/realtime`.
2. Increased `503` responses on `/api/transcription/realtime`.
3. Session records accumulating in `failed` or `expired` state beyond the retention window.
4. Missing or stale owner instance heartbeats in `/api/admin?type=realtime`.

If `409` or `503` rises in production, inspect these first:

1. Redis connectivity from every application instance.
2. Whether the owner instance still reports heartbeat.
3. Whether proxy/session affinity changes caused unusually high cross-instance routing.

## Default Safety Limits

- `MAX_REALTIME_SESSIONS_PER_USER=3`
- `MAX_REALTIME_CHUNK_BYTES=2097152`
- `MAX_REALTIME_SESSION_BYTES=10485760`

These defaults are intentionally conservative for launch. Raise them only with corresponding monitoring on memory, ffmpeg load, and upstream ASR quota usage.

## Load Test Plan

Run the following scenarios before enabling full horizontal scale:

1. Single-session concurrent append:
  - One active session.
  - 20-50 concurrent `append` requests with small audio chunks.
  - Verify ordered partial transcript handling and no duplicate finalization.
2. Multi-user burst start:
  - 20 users concurrently send `start`.
  - Validate `429` behavior once per-user active-session limit is exceeded.
3. Oversized chunk rejection:
  - Send chunks slightly above `MAX_REALTIME_CHUNK_BYTES`.
  - Verify `413` is returned before upstream websocket work begins.
4. Owner failure drill:
  - Start a session on instance A.
  - Route `append` through instance B.
  - Stop instance A or block its Redis heartbeat.
  - Verify the API returns `503` rather than hanging.

## Known Limits

This release still keeps the live websocket handle process-local to the owner instance.

That means:

- metadata is shared through SQLite
- routing is coordinated through Redis
- instance loss during an active realtime ASR session still terminates that specific session
- Redis coordination removes wrong-instance rejection for valid cross-instance traffic, but it is not a live-session failover system
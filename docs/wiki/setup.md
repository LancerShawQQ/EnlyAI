# EnlyAI Classroom — Setup & Operations

This document covers everything needed to run, test, and deploy the project: dependencies, environment variables, scripts, and operational caveats collected from the codebase and `docs/`.

---

## 1. Requirements

| Tool | Version |
| --- | --- |
| Node.js | `>=20.9.0` (the project pins `node@22-alpine` in the Docker image) |
| pnpm | `>=10` (locked to `pnpm@10.28.0` via `packageManager`) |
| OS | Linux (Alpine used in Docker) / macOS / WSL2 |

The build requires native compilation for `better-sqlite3`, `sharp`, and `@napi-rs/canvas`. On Alpine this means `python3 build-base g++ cairo-dev pango-dev jpeg-dev giflib-dev librsvg-dev` (see [Dockerfile](file:///workspace/Dockerfile)).

---

## 2. Install

```bash
pnpm install
```

`postinstall` builds the two local workspace packages:

```text
packages/mathml2omml  → npm run build
packages/pptxgenjs    → npm run build
```

`pnpm.onlyBuiltDependencies` whitelists native builds (`better-sqlite3`, `esbuild`, `@napi-rs/canvas`); `sharp` and `unrs-resolver` are explicitly ignored.

---

## 3. Environment Variables

Create `.env.local` at the repo root. The full list of relevant knobs (split by surface) is:

### 3.1 Required for LLM (server-side keys)

| Variable | Used by |
| --- | --- |
| `OPENAI_API_KEY` | `lib/ai/providers.ts` → OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `GOOGLE_API_KEY` | Google Gemini |
| `MINIMAX_API_KEY`, `MINIMAX_BASE_URL` | MiniMax (Anthropic-compatible) |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL` | DeepSeek (OpenAI-compatible) |
| `GLM_API_KEY`, `GLM_BASE_URL` | GLM (Zhipu) |
| `QWEN_API_KEY`, `DASHSCOPE_API_KEY`, `QWEN_BASE_URL` | Qwen / DashScope |
| `DOUBAO_API_KEY`, `DOUBAO_BASE_URL` | Doubao (Volcengine) |
| `GROK_API_KEY`, `GROK_BASE_URL` | Grok (xAI) |
| `OLLAMA_BASE_URL` | Ollama (local) |

Each provider also has a generic `*_PROXY` override consumed by [lib/server/proxy-fetch.ts](file:///workspace/lib/server/proxy-fetch.ts).

### 3.2 Required for TTS / ASR

`lib/server/provider-config.ts` reads both per-provider YAML and env vars. Common knobs:

| Provider | Env vars |
| --- | --- |
| OpenAI TTS / Whisper | `OPENAI_API_KEY` |
| Azure TTS | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` |
| Qwen TTS/ASR (DashScope) | `DASHSCOPE_API_KEY` |
| GLM TTS | `GLM_API_KEY` |
| Doubao TTS | `DOUBAO_API_KEY` |
| Browser native | (no env) |

### 3.3 Required for image / video / PDF / web search

| Domain | Vars |
| --- | --- |
| Image (Kling/MiniMax/Grok/Qwen/Seedream/…) | `*_API_KEY`, `*_BASE_URL` |
| Video (Veo/Seedance/…) | `*_API_KEY`, `*_BASE_URL` |
| PDF (MinerU) | `MINERU_API_KEY` |
| Web search (Tavily) | `TAVILY_API_KEY` |

### 3.4 Application

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET` | **Required in production** for session JWT. Read via bracket access (`process.env['JWT_SECRET']`) to survive bundler inlining. |
| `AUTH_SECURE_COOKIE` | Set to `false` to disable the `Secure` cookie flag (e.g. for HTTP preview deploys). |
| `NODE_ENV` | Standard. Controls logging, secure cookie, JWT secret enforcement. |
| `HOSTNAME`, `PORT` | Bind address for `custom-server.mjs` (default `0.0.0.0:8000`). |
| `START_HOST` | Alternative to `HOSTNAME` used by the `start` script. |
| `NEXT_DIST_DIR` | Override `.next` directory (useful for parallel Playwright runs). |
| `NEXT_INTERNAL_PORT` | Inner Next.js port used by the custom server. Defaults to `PORT + 1`. |
| `VERCEL` | When set, disables the `output: 'standalone'` override. |
| `ALLOWED_FRAME_ANCESTORS` | Extra CSP `frame-ancestors` entries. |
| `REALTIME_REDIS_URL` / `REDIS_URL` | Redis URL for cross-instance realtime coordination. |
| `REDIS_CONNECT_TIMEOUT_MS` | Redis connect timeout (default 5000). |
| `REALTIME_INSTANCE_ID` | Override runtime instance ID (default `hostname:pid:uuid`). |
| `NEXT_PUBLIC_SKIP_AUTH` | When `true`, the client uses a hardcoded test user. |
| `NEXT_PUBLIC_E2E_LESSON_DURATION_SECONDS` | E2E test override for lesson duration. |
| `NEXT_PUBLIC_E2E_LESSON_GRACE_SECONDS` | E2E test grace period. |
| `VITEST_LOAD_DOTENV_LOCAL` | Set to `true` to load `.env.local` for Vitest. |

### 3.5 Optional: `server-providers.yml`

When running a shared classroom server, [lib/server/provider-config.ts](file:///workspace/lib/server/provider-config.ts) loads `server-providers.yml` (mounted into the container at `/app/server-providers.yml` by [docker-compose.yml](file:///workspace/docker-compose.yml)). The schema:

```yaml
providers:
  openai:
    apiKey: sk-...
    baseUrl: https://api.openai.com/v1
    models: [gpt-5.4, gpt-5.4-mini]
tts:
  qwen:
    apiKey: sk-...
    baseUrl: https://dashscope.aliyuncs.com/api/v1
asr:
  qwen:
    apiKey: sk-...
pdf:
  mineru:
    apiKey: sk-...
image:
  kling:
    apiKey: sk-...
video:
  veo:
    apiKey: sk-...
webSearch:
  tavily:
    apiKey: sk-...
```

The `/api/server-providers` route exposes only IDs and metadata to the client.

---

## 4. Scripts

### 4.1 From `package.json`

| Script | Purpose |
| --- | --- |
| `pnpm dev` | `next dev` (HTTP only; WebSocket unavailable) |
| `pnpm dev:lan` | `next dev` bound to `0.0.0.0:8000` |
| `pnpm dev:clean` | Cleans runtime artifacts then starts dev |
| `pnpm build` | `next build --webpack` then `build:ws` |
| `pnpm build:ws` | Bundles the CJS WebSocket handler |
| `pnpm start` | Production via `custom-server.mjs` (default port 8000) |
| `pnpm start:lan` | Alias for `start` |
| `pnpm start:standalone` | Direct invocation of `scripts/start-standalone.mjs` |
| `pnpm clean:runtime` | Removes stale runtime files |
| `pnpm lint` | ESLint |
| `pnpm check` | Prettier --check |
| `pnpm format` | Prettier --write |
| `pnpm test` | Vitest run |
| `pnpm test:e2e` | Playwright |
| `pnpm test:e2e:clean` | Cleans then runs Playwright |
| `pnpm test:e2e:deployed:voice` | Voice stress against an already-deployed URL |
| `pnpm test:e2e:reuse` | Reuses an existing Playwright webserver |
| `pnpm test:e2e:ui` | Playwright UI mode |

### 4.2 Helper scripts in `scripts/`

See [modules.md §`scripts/`](./modules.md#scripts).

---

## 5. Running Locally

```bash
# 1. Install
pnpm install

# 2. Configure
cp .env.example .env.local  # if available; otherwise create one with at least one LLM key

# 3. Dev
pnpm dev          # or pnpm dev:lan for LAN access

# 4. Build + serve (production)
pnpm build
pnpm start        # listens on PORT (default 8000)
```

Health check: `GET /api/health`.

WebSocket (production only): `ws://HOSTNAME:PORT/ws/classroom?token=<jwt>`.

---

## 6. Testing

### 6.1 Vitest (unit / integration)

```bash
pnpm test
```

- `vitest.config.ts` defines the test runner; `vitest.eval.config.ts` adds a separate config for evaluation tests.
- Tests live in `tests/`, mirroring the `lib/` layout.
- `tests/setup-env.ts` is the global setup file.

If a test needs a developer secret from `.env.local`, run:

```bash
VITEST_LOAD_DOTENV_LOCAL=true pnpm test
```

### 6.2 Playwright (E2E)

```bash
# Cold run: clean + boot its own server
pnpm test:e2e:clean

# Reuse a running server for iteration
PLAYWRIGHT_REUSE_WEBSERVER=1 pnpm playwright test e2e/tests/returning-student-hydration.spec.ts --project=chromium

# Custom port + dist dir to avoid clashing with another server
PLAYWRIGHT_PORT=3305 PLAYWRIGHT_DIST_DIR=.next-playwright-3305 \
JWT_SECRET=test-secret \
NEXT_PUBLIC_E2E_LESSON_DURATION_SECONDS=12 \
NEXT_PUBLIC_E2E_LESSON_GRACE_SECONDS=1 \
pnpm playwright test e2e/tests/classroom-interaction.spec.ts --project=chromium --reporter=line

# UI mode
pnpm test:e2e:ui

# Deployed URL
PLAYWRIGHT_BASE_URL=${PLAYWRIGHT_BASE_URL:-https://www.enlyai.com} \
PLAYWRIGHT_SKIP_WEBSERVER=1 \
pnpm test:e2e:deployed:voice
```

---

## 7. Deployment

### 7.1 Docker (recommended)

[Dockerfile](file:///workspace/Dockerfile) is a 4-stage build:

1. `base` — `node:22-alpine` with corepack + pnpm.
2. `deps` — installs full deps (incl. dev) with native build tools.
3. `builder` — runs `pnpm build`.
4. `runner` — copies standalone output **and the full pnpm-populated `node_modules`** (to work around the `better-sqlite3` / `bindings` standalone-tracing bug documented in `next.config.ts` and the Dockerfile comments).

Compose (see [docker-compose.yml](file:///workspace/docker-compose.yml)):

```yaml
services:
  enlyai:
    image: ${DOCKER_IMAGE:-}
    build: { context: . }
    ports: ["${ENLYAI_PORT:-8000}:8000"]
    env_file: [.env.local]
    environment:
      HOSTNAME: 0.0.0.0
      PORT: 8000
      NODE_ENV: production
      JWT_SECRET: ${JWT_SECRET}
    volumes:
      - ./server-providers.yml:/app/server-providers.yml:ro
      - enlyai-data:/app/data
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:8000/api/health')..."]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
    restart: unless-stopped
    deploy:
      resources:
        limits: { memory: 2G }
        reservations: { memory: 512M }
volumes:
  enlyai-data:
```

Notable details:

- `environment: > env_file:` for `JWT_SECRET` — the env-file value survives across deploys (the historical bug was that `env_file` values were silently dropped on compose v2).
- The `/app/data` volume persists SQLite + uploaded media.
- Logs are rotated via the `json-file` driver (`max-size: 10m`, `max-file: 3`).

### 7.2 Standalone Node (no Docker)

```bash
pnpm build
HOSTNAME=0.0.0.0 PORT=8000 pnpm start
```

This runs `scripts/start-standalone.mjs`, which:

1. Copies `public/` and `.next/static/` into `.next/standalone/`.
2. Copies `custom-server.mjs`.
3. Spawns `custom-server.mjs`, which in turn spawns `server.js` (Next standalone) on `127.0.0.1:NEXT_INTERNAL_PORT` and proxies HTTP traffic to it. WebSocket upgrades for `/ws/classroom` are handled in-process.

### 7.3 Vercel

`next.config.ts` detects `VERCEL=1` and disables the `standalone` output. Standard Vercel build settings work.

### 7.4 Deployment notes

- See [docs/deployment/aliyun-standalone-deploy.md](file:///workspace/docs/deployment/aliyun-standalone-deploy.md) for the China-region Aliyun guide.
- See [docs/deployment/github-actions-deploy.md](file:///workspace/docs/deployment/github-actions-deploy.md) for CI/CD.
- See [docs/deployment/enlyai-migration.md](file:///workspace/docs/deployment/enlyai-migration.md) before upgrading an existing deployment (service names, port vars, data volumes).
- See [docs/deployment/standalone-deploy-pitfalls.md](file:///workspace/docs/deployment/standalone-deploy-pitfalls.md) for known issues.
- See [docs/deployment/realtime-asr-release-20260509.md](file:///workspace/docs/deployment/realtime-asr-release-20260509.md) for the realtime ASR rollout.
- See [docs/deployment/zego-digital-human.md](file:///workspace/docs/deployment/zego-digital-human.md) for digital human setup.
- See [docs/deployment/admin-console.md](file:///workspace/docs/deployment/admin-console.md) for the admin console.
- See [docs/deployment/domain-diagnosis-20260430.md](file:///workspace/docs/deployment/domain-diagnosis-20260430.md) for a real-world domain debugging case study.

---

## 8. Operational Runbook

### 8.1 Logs

- All server logs flow through `lib/logger.ts` (tagged by module).
- `createLogger('ClassroomWs').info(…)` is the canonical way to add context.
- For correlation, every request/server includes a `getRuntimeInstanceId()` value.

### 8.2 Database

- SQLite file lives in `/app/data/` inside the container (mounted as the `enlyai-data` volume).
- Schema is created on boot by [lib/db/index.ts](file:///workspace/lib/db/index.ts). Optional columns are added with `CREATE TABLE IF NOT EXISTS` style guards — safe to run repeatedly.
- For backups, snapshot the volume.

### 8.3 Caches

- Prompts are loaded from Markdown via [lib/generation/prompts/loader.ts](file:///workspace/lib/generation/prompts/loader.ts); use `clearPromptCache()` after editing.
- Client-side caches live in `localStorage` (Zustand `persist`) and IndexedDB (Dexie).

### 8.4 Health

- `GET /api/health` is used by the Docker healthcheck.
- For deeper diagnostics, see [scripts/probe-enly.mjs](file:///workspace/scripts/probe-enly.mjs) and the Playwright smoke specs under `e2e/tests/deployed-*.spec.ts`.

### 8.5 Common pitfalls

- **First-run auth failure** — `JWT_SECRET` is required in production. The `lib/auth/index.ts` logs the resolved environment to make this easier to debug.
- **`Cannot find module 'bindings'`** — Caused by Next.js standalone not following dynamic `require()` from native modules. The Dockerfile intentionally replaces the partial `node_modules` with the full pnpm tree (see comments in [Dockerfile](file:///workspace/Dockerfile)).
- **WebSocket 404 in dev** — The custom server only runs in production. Use `pnpm start` (after `pnpm build`) to test WS.
- **TTS streaming vs. fallback** — Providers without streaming TTS still fall back to `/api/generate/tts`; the front-end prefers `/api/generate/tts-stream` when available.

---

## 9. Lint, Format, Type-check

```bash
pnpm lint      # ESLint (next config)
pnpm check     # Prettier --check
pnpm format    # Prettier --write
```

`tsconfig.json` extends a strict Next.js + project config. The two local packages (`packages/mathml2omml`, `packages/pptxgenjs`) have their own `tsconfig.json` / `rollup.config.*` and are built independently.

---

## 10. CI

[`.github/workflows/ci.yml`](file:///workspace/.github/workflows/ci.yml) and [`.github/workflows/deploy.yml`](file:///workspace/.github/workflows/deploy.yml) cover CI and deploy. Issue and PR templates live under `.github/ISSUE_TEMPLATE/` and `.github/pull_request_template.md`.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `/api/auth/*` returns 500 with `Cannot find module 'bindings'` | Standalone tracing missed `better-sqlite3` transitive deps | Re-build with the shipped Dockerfile (which replaces `node_modules`) or run `pnpm start:standalone` from a full install |
| `JWT must be provided` on first request | Missing `JWT_SECRET` in production env | Set `JWT_SECRET` in `.env.local` and restart |
| `Tavily 400` on long queries | Query > 400 chars | Truncation is automatic in `lib/web-search/tavily.ts`; verify the source query |
| Microphone never activates | Permissions / HTTPS required | `use-browser-asr` requires `getUserMedia`; some browsers require HTTPS for production |
| Playwright `port 3302` in use | Another test server is running | Set `PLAYWRIGHT_PORT` + `PLAYWRIGHT_DIST_DIR` (see §6.2) |
| Custom server starts but `/ws/classroom` closes immediately | `JWT_SECRET` mismatch between server and client | Re-issue JWTs and verify `extractToken` in `lib/server/classroom-websocket.ts` |

For deeper debugging, see `docs/deployment/standalone-deploy-pitfalls.md` and `SECURITY_AUDIT_REPORT.md`.

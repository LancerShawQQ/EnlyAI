# EnlyAI Classroom — Architecture

This document explains the high-level system architecture, the data flow inside a live classroom, the provider system, and the persistence model. It is meant to be read alongside the module reference ([modules.md](./modules.md)) and the API surface ([api-reference.md](./api-reference.md)).

---

## 1. System Topology

The application is a single Next.js 16 app that runs in two modes:

1. **Development** — `next dev` handles HTTP only. WebSocket traffic is **not** available (this is documented in the custom server entry).
2. **Production / Standalone** — `next build` produces a Next.js standalone bundle, and a custom Node entrypoint ([custom-server.mjs](file:///workspace/custom-server.mjs)) spawns `server.js` and adds a `ws` `WebSocketServer` for `/ws/classroom`. The two servers communicate by proxying HTTP requests to the inner Next process on `127.0.0.1:NEXT_INTERNAL_PORT`.

```text
┌──────────────────────────────────────────────────────────────┐
│                       Browser (React 19)                    │
│  components/stage.tsx · components/chat/chat-area.tsx       │
│  components/scene-renderers/* · components/slide-renderer/* │
│  use-* hooks (asr, tts, ws-chat-session, theme, i18n)       │
└──────────────────────┬─────────────────────┬─────────────────┘
                       │ HTTP/SSE            │ WebSocket
                       │ (Next.js)           │ /ws/classroom
                       ▼                     ▼
┌──────────────────────────────────────────────────────────────┐
│ custom-server.mjs  (Node, port 8000)                         │
│   ├─ spawn server.js  (Next.js standalone, internal port)    │
│   └─ WebSocketServer  →  classroom-websocket.cjs             │
└──────────────┬─────────────────────┬─────────────────────────┘
               │                     │
               ▼                     ▼
       app/api/**/route.ts     lib/server/classroom-websocket.ts
       (HTTP)                  (Audio/ASR/LLM orchestration)
```

Auxiliary sidecars (read by both processes):

- **Redis** (`ioredis`) — realtime ASR session registry, cross-instance coordination. Optional but recommended for multi-replica deployment.
- **SQLite** (`better-sqlite3` + Drizzle) — users, sessions, learning history, lesson analytics, payment orders, realtime transcription logs.
- **Object storage** — currently a `noop` provider; pluggable via [lib/storage](file:///workspace/lib/storage).
- **External APIs** — LLM (OpenAI/Anthropic/Google/MiniMax/DeepSeek/GLM/…), TTS (Qwen realtime, OpenAI, Azure, GLM, Doubao, Browser), ASR (Qwen, OpenAI Whisper, Browser), image (Kling, MiniMax, Grok, Qwen, Seedream, Seedance, Veo, Nano Banana), video, PDF (MinerU), web search (Tavily), digital human (ZEGO).

---

## 2. Request Lifecycle — "Generate a Course"

This is the path from "user clicks Generate" to a classroom ready to play.

```text
1. Frontend (generation-preview/page.tsx)
   └─ POST /api/generate-classroom  (job runner kicks off)
2. app/api/generate-classroom/route.ts
   └─ createGenerationJob() → runClassroomJob() (lib/server/classroom-job-runner.ts)
3. Stage 1 — Outlines
   lib/generation/outline-generator.ts
   └─ streamLLM("requirements-to-outlines") with web-search augmentation
   └─ emits SceneOutlines[] to job store
4. Stage 2 — Scenes (per outline, in batches of 3 with retries)
   lib/generation/scene-generator.ts
   ├─ streamLLM("slide-content" | "quiz-content" | "interactive-html" | "pbl-content" | …)
   └─ streamLLM("{type}-actions") to convert content into Scene.actions[]
5. Optional: media (image/video) prefetch
   lib/media/media-orchestrator.ts
   └─ concurrency-limited fan-out to /api/generate/image and /api/generate/video
   └─ stores blobs in IndexedDB (Dexie) via lib/utils/database.ts
6. Optional: TTS prefetch
   lib/hooks/use-scene-generator.ts
   └─ POSTs each speech action to /api/generate/tts-stream
7. Classroom JSON assembled, saved to:
   ├─ SQLite (server, on completion)
   └─ IndexedDB (client, via useStageStore)
8. Frontend navigates to /classroom/[id] which hydrates from the same store.
```

Key invariants:

- All prompts live in `lib/generation/prompts/templates/*` (Markdown) and `snippets/*`, with `{{snippet:…}}` and `{{variable}}` interpolation in [lib/generation/prompts/loader.ts](file:///workspace/lib/generation/prompts/loader.ts).
- The pipeline is **resumable**: job state lives in `lib/server/classroom-job-store.ts` (in-memory + optional Redis) and the client polls `/api/generate-classroom/[jobId]`.
- Stage-2 retries fall back to a deterministic builder (`lib/generation/scene-builder.ts`) when the LLM output is unrepairable (see `json-repair.ts` and `applyOutlineFallbacks`).

---

## 3. Request Lifecycle — "Live Classroom"

Once a course is generated, the user enters `/classroom/[id]`. There are two transport options depending on configuration:

### 3.1 HTTP/SSE mode (default)

```text
Browser                            Server
───────                            ──────
POST /api/chat  ──────────────────► stateless-generate.ts
                    ◄──────────────  SSE  (text deltas + tool calls)
SSE events dispatched via process-sse-stream.ts
```

- `app/api/chat/route.ts` validates the request, picks the model via `lib/server/resolve-model.ts`, and calls `statelessGenerate()`.
- `lib/orchestration/stateless-generate.ts` builds a `LangGraph` `StateGraph` (`director → agent_generate → director`) and streams structured events through `eventsource-parser`.
- The frontend processes events in `components/chat/process-sse-stream.ts` and applies them to the `useStageStore` Zustand store.

### 3.2 WebSocket (full-duplex voice) mode

Used when the user enables the dedicated classroom voice engine. The browser opens `ws://…/ws/classroom` and exchanges a binary+JSON protocol.

```text
Browser
  │  PCM audio frames (binary)
  │  text/control messages (JSON)
  ▼
custom-server.mjs → classroom-websocket.cjs
  │  Auth: extractToken() from cookie or `?token=` query
  │  Session: createSession() (lib/server/classroom-ws-session-store.ts)
  │
  ├─ ASR path
  │    ├─ FunASR realtime (bailian-realtime.ts) — primary
  │    └─ Qwen ASR / Whisper (asr-providers.ts) — fallback
  │
  ├─ LLM path
  │    └─ stateless-generate.ts (same as HTTP mode)
  │
  └─ TTS path
       ├─ Qwen Realtime TTS (bailian-realtime.ts) — streaming
       └─ TTS segmenter (streaming-tts-segmenter.ts) → PCM
```

Latency / pacing is governed by `lib/learning/scene-pacing.ts` (`LessonRhythmPhase` + `HardPacingAction`) and `lib/orchestration/active-classroom-engine.ts`. Server-side `lib/learning/lesson-pace-controller.ts` and `lib/learning/lesson-progress-enforcer.ts` guarantee that scene timing and progress reports are coherent.

### 3.3 Playback engine

Both online and offline classroom mode share the same `Action` types and the same `PlaybackEngine` in [lib/playback/engine.ts](file:///workspace/lib/playback/engine.ts). The engine is a finite state machine (`idle → playing → paused → live`) and consumes `Scene.actions[]` directly through `lib/action/engine.ts`.

- **Online**: actions are produced by the streaming Director graph as they arrive.
- **Offline / playback**: actions are replayed from a serialized lesson. The user can still `pause/resume` and trigger a discussion at any time.

---

## 4. Provider System

EnlyAI is **multi-provider by design**. Each external capability (LLM, TTS, ASR, image, video, PDF, web-search, digital human) has:

1. A **client-side settings store** ([lib/store/settings.ts](file:///workspace/lib/store/settings.ts)) that holds per-provider config (apiKey, baseUrl, model, voice, customVoices, isServerConfigured, …).
2. A **constants registry** (e.g. [lib/audio/constants.ts](file:///workspace/lib/audio/constants.ts)) that defines provider metadata, models, voices, languages — client-safe (no Node imports).
3. A **provider implementation** (e.g. [lib/audio/tts-providers.ts](file:///workspace/lib/audio/tts-providers.ts), [lib/audio/asr-providers.ts](file:///workspace/lib/audio/asr-providers.ts)) that switches on provider ID.
4. A **server-side loader** ([lib/server/provider-config.ts](file:///workspace/lib/server/provider-config.ts)) that reads `server-providers.yml` (or environment variables) and exposes server-configured providers via `/api/server-providers`. Server keys never leave the server.
5. A **verification endpoint** (e.g. `/api/verify-model`, `/api/verify-image-provider`) used by the settings UI to ping a key before saving.

### 4.1 LLM provider layout

```text
lib/types/provider.ts          – ProviderId union, ModelInfo, ThinkingConfig
lib/ai/providers.ts            – PROVIDERS registry (openai, anthropic, google, minimax, …)
lib/ai/llm.ts                  – callLLM / streamLLM (unified facade)
lib/ai/thinking-context.ts     – server-only AsyncLocalStorage for thinking budget
lib/server/resolve-model.ts    – resolves a providerId + modelId to a LanguageModel
```

Adding a provider = (a) add a new entry to `PROVIDERS`, (b) wire it into `lib/server/resolve-model.ts`, (c) add icons/translations, (d) optionally add server-side keys to `server-providers.yml`.

### 4.2 Audio provider layout

```text
lib/audio/types.ts             – TTSProviderId, ASRProviderId, voice types
lib/audio/constants.ts         – TTS_PROVIDERS, ASR_PROVIDERS registries
lib/audio/tts-providers.ts     – generateTTS() switch
lib/audio/asr-providers.ts     – transcribeAudio() switch
lib/audio/bailian-realtime.ts  – FunASR + Qwen realtime WS streams
lib/audio/omni-realtime.ts     – Qwen Omni S2S session manager
lib/audio/voice-resolver.ts    – picks the active voice from settings
lib/audio/asr-selection.ts     – picks the active ASR provider from settings
lib/audio/streaming-tts-segmenter.ts – chunks streaming TTS into speakable segments
```

### 4.3 Media provider layout

`lib/media/{image-providers,video-providers}.ts` are small registries. The actual HTTP calls live in [lib/media/adapters/*](file:///workspace/lib/media/adapters) — one adapter per provider (Grok, Kling, MiniMax, Veo, Seedance, Seedream, Nano Banana, Qwen). The orchestrator ([lib/media/media-orchestrator.ts](file:///workspace/lib/media/media-orchestrator.ts)) runs them with a concurrency cap and stores results in IndexedDB.

---

## 5. Persistence Model

### 5.1 Server (SQLite + Drizzle)

File: [lib/db/schema.ts](file:///workspace/lib/db/schema.ts). Singleton connection: [lib/db/index.ts](file:///workspace/lib/db/index.ts) (uses `better-sqlite3`, applies optional-column migrations at boot).

| Table | Purpose |
| --- | --- |
| `users` | Email / password hash / profile |
| `sessions` | Server-side session records backing the JWT cookie |
| `learning_progress` | Per-language totals: minutes, sessions, streak, average score |
| `lesson_history` | Per-lesson record: teacher, language, topic, scores, feedback |
| `lesson_session_analytics` | Process-level analytics (turn counts, latency, drill recommendations) |
| `teacher_memories` | Returning-student memory for continuity |
| `realtime_transcription_sessions` | Server-side ASR session log (with retention) |
| `payment_orders` | Order state, provider refs, idempotency keys |
| `usage_logs` (in-memory) | LLM/TTS call telemetry ([lib/server/usage-logger.ts](file:///workspace/lib/server/usage-logger.ts)) |

### 5.2 Client (IndexedDB via Dexie)

File: [lib/utils/database.ts](file:///workspace/lib/utils/database.ts). Stores:

- `media` — generated image / video blobs
- `audio` — TTS audio blobs keyed by `audioId`
- `agents` — generated agent configs
- `thumbnails` — slide thumbnails
- `history` — chat history snapshots

### 5.3 Client state (Zustand, persisted)

| Store | Purpose |
| --- | --- |
| `useStageStore` | The active course: scenes, actions, current scene, playback progress |
| `useCanvasStore` | Canvas element selection / drag state |
| `useSnapshotStore` | Undo/redo snapshots for slides |
| `useKeyboardStore` | Hotkey state |
| `useSettingsStore` | Provider, model, voice, language settings |
| `useAuthStore` | Client auth (test user fallback) |
| `useUserMemoryStore` | Per-user memory for returning-student continuity |
| `useWhiteboardHistoryStore` | Whiteboard stroke history |
| `useMediaGenerationStore` | In-flight media generation jobs |
| `useUsageTrackingStore` | Client usage telemetry |
| `useTeacherRegistry` | Persisted virtual teacher registry |
| `useUserProfile` | Profile state (avatar, bio, native language) |

---

## 6. Auth & Access Control

- **JWT cookie** — `enlyai_session` (HS256 via `jose`). Library: [lib/auth/index.ts](file:///workspace/lib/auth/index.ts).
- **Password hashing** — `bcryptjs` (server only).
- **Access code gate** — `components/access-code-guard.tsx` blocks the app unless a valid code is presented; the API routes are at `/api/access-code/{status,verify}`.
- **Admin gate** — `/admin/login` and the admin API routes use a separate `bcrypt` + cookie scheme; routes under `/api/admin/*` enforce it.
- **Provider config** — server-side `server-providers.yml` is read once at boot and exposed read-only through `/api/server-providers` (never returns API keys).

---

## 7. Theming, i18n, and Accessibility

- **Theme** — `next-themes` wrapped in `lib/hooks/use-theme.tsx`; CSS variables defined in [app/globals.css](file:///workspace/app/globals.css).
- **i18n** — `react-i18next` + `i18next-resources-to-backend`. Five locales: `zh-CN`, `en-US`, `ja-JP`, `ru-RU`, `ar-SA` (RTL). See [lib/i18n/locales.ts](file:///workspace/lib/i18n/locales.ts) and `lib/i18n/locale-detection.ts`. Translation guide: `lib/i18n/TRANSLATION_GUIDE.md`.
- **Fonts** — Local Inter (`@fontsource-variable/inter`) + `GeistMono`. Loaded in [app/layout.tsx](file:///workspace/app/layout.tsx).
- **Animation** — `motion` (Framer Motion) and `animate.css`.

---

## 8. Build, Run, Deploy

Full instructions live in [setup.md](./setup.md). Summary:

```bash
pnpm install
pnpm dev                          # next dev (HTTP only)
pnpm dev:lan                      # bind 0.0.0.0:8000
pnpm build                        # next build --webpack + build:ws
pnpm start                        # production via custom-server.mjs
pnpm test                         # vitest
pnpm test:e2e                     # playwright
```

Deployment uses a multi-stage Docker build (see [Dockerfile](file:///workspace/Dockerfile)) with two notable fixes baked in for `better-sqlite3`'s transitive native deps (`bindings`, `file-uri-to-path`). The custom server reads `JWT_SECRET` via bracket-access to survive bundler inlining.

---

## 9. Observability

- **Logging** — `lib/logger.ts` returns a tagged logger; used everywhere via `createLogger('Name')`.
- **Usage logs** — In-memory LLM/TTS call log surfaced via `/api/admin/track`.
- **Visitor tracking** — Lightweight `components/visitor-tracker.tsx` records visits (opt-in via env).
- **Server instance ID** — `lib/server/runtime-instance.ts` exposes `getRuntimeInstanceId()` for log correlation.

---

## 10. Security Posture

- **SSRF guard** — [lib/server/ssrf-guard.ts](file:///workspace/lib/server/ssrf-guard.ts) validates outbound URLs (used by media proxy, TTS proxy, web search).
- **Proxy fetch** — [lib/server/proxy-fetch.ts](file:///workspace/lib/server/proxy-fetch.ts) centralises `undici.fetch` config (timeouts, redirects, proxy).
- **Frame headers** — `next.config.ts` sets CSP `frame-ancestors` (and `X-Frame-Options` when no override is set).
- **Body size** — `experimental.proxyClientMaxBodySize: '200mb'` to allow large media uploads.
- **Rate limiting** — Implemented inside per-route helpers (e.g. `/api/auth/login`).
- **Secret handling** — `JWT_SECRET` and other secrets are always read via `process.env['NAME']` bracket access to prevent bundler inlining.
- **Audit** — `SECURITY_AUDIT_REPORT.md` and `SECURITY_FIX_GUIDE.md` document historical issues and fixes.

See [SECURITY.md](file:///workspace/SECURITY.md) for full policy.

# EnlyAI Classroom — API Reference

This document covers the public HTTP surface (`app/api/**/route.ts`), the WebSocket protocol for the live classroom, and the most important server-side SDK functions exposed by `lib/`.

Conventions:

- All JSON responses use the shape `{ success: boolean, …payload, errorCode?, error? }` (helper: `apiSuccess` / `apiError` in [lib/server/api-response.ts](file:///workspace/lib/server/api-response.ts)).
- Streaming responses use `text/event-stream` (SSE) for LLM chat / outline streaming, and chunked `audio/*` for TTS.
- Auth is the `enlyai_session` JWT cookie, validated via `getCurrentUser()` in [lib/auth/index.ts](file:///workspace/lib/auth/index.ts).
- CORS / frame-ancestors are configured globally in [next.config.ts](file:///workspace/next.config.ts).

---

## 1. HTTP Routes

> Paths below are relative to the deployment origin (default `http://localhost:8000`). All routes are Next.js App Router handlers unless noted.

### 1.1 Auth

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/auth/register` | [route.ts](file:///workspace/app/api/auth/register/route.ts) | Create a user; returns `{ user, sessionToken }` and sets cookie. |
| `POST` | `/api/auth/login` | [route.ts](file:///workspace/app/api/auth/login/route.ts) | Email + password login. In-memory rate limit (8 failures / 15 min). |
| `POST` | `/api/auth/logout` | [route.ts](file:///workspace/app/api/auth/logout/route.ts) | Clears the session cookie and revokes the session. |
| `GET`  | `/api/auth/me` | [route.ts](file:///workspace/app/api/auth/me/route.ts) | Returns the current user (or `null`). |

### 1.2 Access code

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/access-code/status` | [route.ts](file:///workspace/app/api/access-code/status/route.ts) | Returns whether an access code is required. |
| `POST` | `/api/access-code/verify` | [route.ts](file:///workspace/app/api/access-code/verify/route.ts) | Verifies a code and sets a cookie. |

### 1.3 Chat & classroom

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/chat` | [route.ts](file:///workspace/app/api/chat/route.ts) | **Stateless multi-agent chat (SSE).** Streams `text deltas` + tool calls. |
| `POST` | `/api/classroom` | [route.ts](file:///workspace/app/api/classroom/route.ts) | Persists a generated `Stage` + `Scene[]`. Returns `{ id, url }`. |
| `GET`  | `/api/classroom-media/[classroomId]/[...path]` | [route.ts](file:///workspace/app/api/classroom-media/%5BclassroomId%5D/%5B...path%5D/route.ts) | Streams classroom-scoped media (SSRF-guarded). |
| `POST` | `/api/pbl/chat` | [route.ts](file:///workspace/app/api/pbl/chat/route.ts) | PBL (Project-Based Learning) chat. |
| `POST` | `/api/quiz-grade` | [route.ts](file:///workspace/app/api/quiz-grade/route.ts) | Grades a quiz submission. |

### 1.4 Course generation

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/generate-classroom` | [route.ts](file:///workspace/app/api/generate-classroom/route.ts) | **Kicks off a generation job** (returns `202` with `jobId` + `pollUrl`). |
| `GET` | `/api/generate-classroom/[jobId]` | [route.ts](file:///workspace/app/api/generate-classroom/%5BjobId%5D/route.ts) | Polls job status (`step`, `message`, partial result, error). |
| `POST` | `/api/generate/scene-outlines-stream` | [route.ts](file:///workspace/app/api/generate/scene-outlines-stream/route.ts) | Stage 1 stream: `requirements → outlines`. |
| `POST` | `/api/generate/scene-content` | [route.ts](file:///workspace/app/api/generate/scene-content/route.ts) | Stage 2: outline → scene content. |
| `POST` | `/api/generate/scene-actions` | [route.ts](file:///workspace/app/api/generate/scene-actions/route.ts) | Stage 2: scene content → action array. |
| `POST` | `/api/generate/agent-profiles` | [route.ts](file:///workspace/app/api/generate/agent-profiles/route.ts) | Generates agent profiles (teacher / classmates). |
| `POST` | `/api/generate/image` | [route.ts](file:///workspace/app/api/generate/image/route.ts) | Generates a single image (server-side fetch). |
| `POST` | `/api/generate/video` | [route.ts](file:///workspace/app/api/generate/video/route.ts) | Generates a single video. |
| `POST` | `/api/generate/tts` | [route.ts](file:///workspace/app/api/generate/tts/route.ts) | Non-streaming TTS (compatibility). |
| `POST` | `/api/generate/tts-stream` | [route.ts](file:///workspace/app/api/generate/tts-stream/route.ts) | **Streaming TTS** (audio bytes). |
| `POST` | `/api/parse-pdf` | [route.ts](file:///workspace/app/api/parse-pdf/route.ts) | PDF parsing (MinerU and others). |

### 1.5 Voice

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/transcription` | [route.ts](file:///workspace/app/api/transcription/route.ts) | One-shot ASR (`multipart/form-data`). |
| `POST` | `/api/transcription/realtime` | [route.ts](file:///workspace/app/api/transcription/realtime/route.ts) | Realtime ASR (FunASR over WS, see protocol below). |
| `GET`/`POST` | `/api/omni-realtime` | [route.ts](file:///workspace/app/api/omni-realtime/route.ts) | Qwen Omni S2S relay: `POST` = control (start/append/commit/cancel/close), `GET` = SSE of `audio_delta` + `transcript_delta` events. |
| `GET` | `/api/azure-voices` | [route.ts](file:///workspace/app/api/azure-voices/route.ts) | List of Azure TTS voices. |

### 1.6 Learning & analytics

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `GET`/`POST` | `/api/learning` | [route.ts](file:///workspace/app/api/learning/route.ts) | Dashboard data (learning loop, trend, next-step drills). Accepts `POST` to record lesson completion. |

### 1.7 Provider configuration

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/server-providers` | [route.ts](file:///workspace/app/api/server-providers/route.ts) | Returns server-configured provider IDs and metadata (no keys). |
| `POST` | `/api/verify-model` | [route.ts](file:///workspace/app/api/verify-model/route.ts) | Pings an LLM provider with a test prompt. |
| `POST` | `/api/verify-image-provider` | [route.ts](file:///workspace/app/api/verify-image-provider/route.ts) | Pings an image provider. |
| `POST` | `/api/verify-video-provider` | [route.ts](file:///workspace/app/api/verify-video-provider/route.ts) | Pings a video provider. |
| `POST` | `/api/verify-pdf-provider` | [route.ts](file:///workspace/app/api/verify-pdf-provider/route.ts) | Pings a PDF provider. |
| `POST` | `/api/web-search` | [route.ts](file:///workspace/app/api/web-search/route.ts) | Web search via Tavily (or stub). |
| `POST` | `/api/proxy-media` | [route.ts](file:///workspace/app/api/proxy-media/route.ts) | SSRF-guarded media proxy. |

### 1.8 Digital human

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/digital-human/zego-token` | [route.ts](file:///workspace/app/api/digital-human/zego-token/route.ts) | Issues a ZEGO token for the digital human room. |

### 1.9 Payments

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/payments/catalog` | [route.ts](file:///workspace/app/api/payments/catalog/route.ts) | Returns the `PAYMENT_PLANS` catalog. |
| `POST` | `/api/payments/checkout` | [route.ts](file:///workspace/app/api/payments/checkout/route.ts) | Creates a checkout session. |
| `GET` | `/api/payments/orders/[orderId]` | [route.ts](file:///workspace/app/api/payments/orders/%5BorderId%5D/route.ts) | Order status. |
| `POST` | `/api/payments/webhooks/[provider]` | [route.ts](file:///workspace/app/api/payments/webhooks/%5Bprovider%5D/route.ts) | Webhook receiver. |
| `POST` | `/api/payments/sandbox/complete` | [route.ts](file:///workspace/app/api/payments/sandbox/complete/route.ts) | Sandbox completion (for `payment-sandbox` UI). |

### 1.10 Admin

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/admin` | [route.ts](file:///workspace/app/api/admin/route.ts) | Admin operations (login, summary, etc.). |
| `GET`/`POST` | `/api/admin/provider-config` | [route.ts](file:///workspace/app/api/admin/provider-config/route.ts) | Read / write `server-providers.yml`. |
| `GET` | `/api/admin/track` | [route.ts](file:///workspace/app/api/admin/track/route.ts) | Usage log snapshot. |

### 1.11 Health

| Method | Path | Source | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/health` | [route.ts](file:///workspace/app/api/health/route.ts) | Liveness probe used by Docker healthcheck. |

---

## 2. WebSocket Protocol — `/ws/classroom`

Implemented in [lib/server/classroom-websocket.ts](file:///workspace/lib/server/classroom-websocket.ts) and exposed by [custom-server.mjs](file:///workspace/custom-server.mjs). Only available in **production / standalone** mode.

### 2.1 Connection

- **URL**: `ws://HOSTNAME:PORT/ws/classroom?token=<jwt>` (token can also come from the `enlyai_session` cookie).
- **Auth**: `authenticateConnection()` calls `verifyToken()`.
- **Session**: server creates a `ClassroomWsSessionEntry` via `createSession()` in [lib/server/classroom-ws-session-store.ts](file:///workspace/lib/server/classroom-ws-session-store.ts).

### 2.2 Frame format

- **Binary frames**: PCM `Int16LE` mono.
  - Client → Server: 16 kHz mic input.
  - Server → Client: 24 kHz TTS output.
- **Text frames**: JSON `ClientMessage` / `ServerMessage` (see [lib/server/classroom-ws-protocol.ts](file:///workspace/lib/server/classroom-ws-protocol.ts)).

### 2.3 Client messages

```ts
type ClientMessage =
  | { type: 'auth'; token: string; lessonConfig: WsLessonConfig }
  | { type: 'audio_commit'; turnId?: string }
  | { type: 'barge_in'; turnId?: string; eventId?: string }
  | { type: 'voice_turn_start'; turnId: string }
  | { type: 'client_latency_mark'; turnId?: string; name: WsClientLatencyMarkName; at: number; detail?: Record<string, unknown> }
  | { type: 'text_input'; text: string }
  | { type: 'scene_ack'; sceneId: string }
  | { type: 'audio_format'; sampleRate: number; encoding: 'pcm_s16le' };
```

`WsLessonConfig`:

```ts
interface WsLessonConfig {
  classroomId: string;
  agentIds: string[];
  sceneIds?: string[];
  totalScenes?: number;
  openingMode?: string;
  language?: string;
  durationMinutes?: number;
  teacherVoice?: { providerId?: string; voiceId?: string; modelId?: string };
}
```

### 2.4 Server messages

Server events include (non-exhaustive; see protocol file for the full set):

- `auth_ok` / `auth_error` — connection-level auth result.
- `asr_partial` / `asr_final` — incremental and committed transcripts.
- `director_state` — Director graph state updates.
- `agent_text` / `agent_action` — agent output fragments.
- `cue_user` — server telling the client to start listening.
- `tts_start` / `tts_audio` (binary) / `tts_end` — speech playback frames.
- `scene_advance` — server-driven scene transition.
- `lesson_complete` — wraps up the lesson.
- `error` — structured error.

### 2.5 Lifecycle

1. Connect → send `auth` with token + lesson config.
2. Stream binary PCM frames. Server pipelines them through FunASR realtime (or Qwen ASR / Whisper as fallback).
3. When the ASR finalises, the server calls `statelessGenerate()` (same path as `/api/chat`) and streams the structured events.
4. For each `speech` action, the server opens a Qwen realtime TTS stream and pushes PCM frames back to the client.
5. The client can interrupt any time with `barge_in` — handled by [lib/server/barge-in-handler.ts](file:///workspace/lib/server/barge-in-handler.ts).

---

## 3. Server-side SDK Functions

These are the most important programmatic entry points. The full inventory lives under `lib/server/`, `lib/orchestration/`, `lib/ai/`, and `lib/audio/`.

### 3.1 LLM

```ts
// lib/ai/llm.ts
import { callLLM, streamLLM } from '@/lib/ai/llm';

await callLLM({ providerId: 'openai', modelId: 'gpt-5.4', prompt: '…', system: '…' });
for await (const chunk of streamLLM({ providerId: 'openai', modelId: 'gpt-5.4', prompt: '…' })) { … }
```

```ts
// lib/server/resolve-model.ts
import { resolveModel } from '@/lib/server/resolve-model';
const model: LanguageModel = resolveModel({ providerId, modelId });
```

### 3.2 Multi-agent orchestration

```ts
// lib/orchestration/stateless-generate.ts
import { statelessGenerate } from '@/lib/orchestration/stateless-generate';
const result = await statelessGenerate({ providerId, modelId, request, signal });
// yields StatelessEvent (text delta, action, cue_user, lesson_complete, error, …)
```

```ts
// lib/orchestration/director-graph.ts
import { createOrchestrationGraph, buildInitialState } from '@/lib/orchestration/director-graph';
// Lower-level: use the LangGraph state graph directly.
```

### 3.3 TTS

```ts
// lib/audio/tts-providers.ts
import { generateTTS, generateTTSStream } from '@/lib/audio/tts-providers';

const { audio, contentType, format } = await generateTTS({
  text: '…',
  ttsProviderId: 'qwen',
  ttsModelId: 'qwen-tts',
  ttsVoice: 'Cherry',
  ttsApiKey: '…',
  ttsBaseUrl: '…',
  ttsSpeed: 1,
  ttsFormat: 'mp3',
  ttsProviderOptions: { … },
});

const { stream, format, contentType } = await generateTTSStream(config, text);
```

### 3.4 ASR

```ts
// lib/audio/asr-providers.ts
import { transcribeAudio } from '@/lib/audio/asr-providers';
const { text, language, segments } = await transcribeAudio({ audio, providerId, modelId, language, apiKey, baseUrl });
```

```ts
// lib/audio/bailian-realtime.ts
import {
  createFunAsrRealtimeTranscriptionSession,
  generateQwenRealtimeTTSStream,
} from '@/lib/audio/bailian-realtime';

const asr = createFunAsrRealtimeTranscriptionSession({ apiKey, baseUrl, modelId, language });
const partial = await asr.appendAudio(buffer, { format: 'pcm', sampleRate: 16000 });
const final = await asr.finish();

const tts = generateQwenRealtimeTTSStream({ text, voice, apiKey, baseUrl, modelId });
for await (const chunk of tts.stream) { /* PCM Int16LE */ }
```

### 3.5 Omni (S2S)

```ts
// lib/audio/omni-realtime.ts + lib/audio/omni-realtime-store.ts
import { startSession, getSession, closeSession } from '@/lib/audio/omni-realtime-store';
const sessionId = startSession({ apiKey, modelId, voice, instructions, turnDetection });
// Append audio, commit, etc. (used by /api/omni-realtime)
```

### 3.6 Media

```ts
// lib/media/media-orchestrator.ts (client)
import { generateMediaForOutlines } from '@/lib/media/media-orchestrator';
await generateMediaForOutlines(outlines, signal);
```

```ts
// lib/media/adapters/*.ts — one function per provider, e.g.
import { generateKlingImage } from '@/lib/media/adapters/kling-adapter';
```

### 3.7 PDF

```ts
// lib/pdf/providers.ts
import { parsePDF } from '@/lib/pdf/providers';
const result = await parsePDF({ file, providerId: 'mineru', apiKey: '…' });
```

### 3.8 Web search

```ts
// lib/web-search/tavily.ts
import { searchWithTavily } from '@/lib/web-search/tavily';
const result = await searchWithTavily({ query, apiKey, maxResults: 5 });
```

### 3.9 Auth

```ts
// lib/auth/index.ts
import {
  getCurrentUser,
  loginUser,
  registerUser,
  logoutUser,
  verifyToken,
  signSession,
  hashPassword,
  comparePassword,
} from '@/lib/auth';
```

### 3.10 Server-side provider config

```ts
// lib/server/provider-config.ts
import {
  getServerProviders,
  getServerTTSProviders,
  resolveLLMApiKey,
  resolveTTSApiKey,
  resolveTTSBaseUrl,
  resolveASRApiKey,
  resolveASRBaseUrl,
  // …per-domain resolvers
} from '@/lib/server/provider-config';
```

### 3.11 Database

```ts
// lib/db/index.ts
import { getDb } from '@/lib/db';
const db = getDb();
const user = await db.select().from(users).where(eq(users.id, id));
```

### 3.12 Payments

```ts
// lib/payments/checkout.ts
import { createPaymentCheckout } from '@/lib/payments/checkout';
const { order, nextAction, providerMode } = await createPaymentCheckout({ planId, method, … });
```

### 3.13 SSRF guard & proxy fetch

```ts
// lib/server/ssrf-guard.ts
import { validateUrlForSSRF } from '@/lib/server/ssrf-guard';
const err = await validateUrlForSSRF(url);

// lib/server/proxy-fetch.ts
import { proxyFetch } from '@/lib/server/proxy-fetch';
const res = await proxyFetch(url, init);
```

### 3.14 WebSocket upgrade

The `/ws/classroom` upgrade is handled by [custom-server.mjs](file:///workspace/custom-server.mjs), which delegates to `classroom-websocket.cjs` (built by `pnpm run build:ws`). Server-only imports are loaded lazily to avoid bundling Node modules into the Next.js process.

---

## 4. Error Codes

`apiError()` uses a small set of canonical codes (see [lib/server/api-response.ts](file:///workspace/lib/server/api-response.ts)):

| Code | Status | Meaning |
| --- | --- | --- |
| `MISSING_REQUIRED_FIELD` | 400 | Required field absent. |
| `INVALID_URL` | 403 | SSRF guard rejected the URL. |
| `INTERNAL_ERROR` | 500 | Unhandled exception. |
| `UNAUTHORIZED` | 401 | Auth required or failed. |
| `RATE_LIMITED` | 429 | Per-route limiter hit. |
| `NOT_FOUND` | 404 | Resource not found. |

Many routes add their own domain-specific codes (e.g. `INVALID_TTS_OPTIONS`, `SSRF_BLOCKED`, `MISSING_API_KEY`); the route file is the source of truth.

---

## 5. Headers, Cookies, Limits

- `Set-Cookie: enlyai_session=<jwt>; HttpOnly; SameSite=Lax; Secure` (when `AUTH_SECURE_COOKIE !== 'false'` and `NODE_ENV === 'production'`).
- `Content-Security-Policy: frame-ancestors 'self' [ALLOWED_FRAME_ANCESTORS]` (see [next.config.ts](file:///workspace/next.config.ts)).
- Body size limit on the proxy: 200 MB (`proxyClientMaxBodySize`).
- Long-running endpoints set `export const maxDuration = 30 | 60` to opt into Vercel/Next.js function timeouts.

---

## 6. Quick Recipes

### Generate a course from the CLI

```bash
curl -X POST http://localhost:8000/api/generate-classroom \
  -H 'Content-Type: application/json' \
  -H "Cookie: enlyai_session=$TOKEN" \
  -d '{
    "requirement": "Plan a 10-minute beginner English lesson about ordering coffee.",
    "lessonLanguage": "en",
    "enableWebSearch": false,
    "enableImageGeneration": true,
    "enableTTS": true
  }'
# → { "jobId": "abc123", "pollUrl": "/api/generate-classroom/abc123", "pollIntervalMs": 5000 }
```

### Stream chat

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -H "Cookie: enlyai_session=$TOKEN" \
  -d '{
    "messages": [{"role":"user","content":"Hello"}],
    "model": { "providerId": "openai", "modelId": "gpt-5.4-mini" }
  }'
```

### Verify a provider before saving

```bash
curl -X POST http://localhost:8000/api/verify-model \
  -H 'Content-Type: application/json' \
  -d '{
    "providerId": "anthropic",
    "apiKey": "sk-ant-…",
    "modelId": "claude-sonnet-4.5"
  }'
```

### Open a live classroom WS

```bash
wscat -c "ws://localhost:8000/ws/classroom?token=$TOKEN"
> { "type": "auth", "token": "<jwt>", "lessonConfig": { "classroomId": "abc", "agentIds": ["teacher-sarah"], "language": "en", "durationMinutes": 10 } }
```

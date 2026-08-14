# EnlyAI Classroom — Module Reference

This document describes each top-level directory and its most important files. Use it together with [architecture.md](./architecture.md) and [api-reference.md](./api-reference.md).

> All paths are relative to the repository root unless noted.

---

## `app/` — Next.js App Router

The Next.js 16 App Router surface. Every file inside `app/api/**/route.ts` is a server-side HTTP endpoint; everything else is a page (or a layout) that renders on the server and hydrates on the client.

### Pages

| Path | Description |
| --- | --- |
| [app/page.tsx](file:///workspace/app/page.tsx) | Landing page → `MarketingHomePage` |
| [app/home-page.tsx](file:///workspace/app/home-page.tsx) | Standalone marketing home component (also reused by `/studio`) |
| [app/studio/page.tsx](file:///workspace/app/studio/page.tsx) | Studio entry (delegates to `home-page.tsx`) |
| [app/about/page.tsx](file:///workspace/app/about/page.tsx) | About page |
| [app/auth/page.tsx](file:///workspace/app/auth/page.tsx) | Login / register UI |
| [app/dashboard/page.tsx](file:///workspace/app/dashboard/page.tsx) | Learning loop dashboard |
| [app/classroom/[id]/page.tsx](file:///workspace/app/classroom/%5Bid%5D/page.tsx) | Live classroom (`<Stage/>`) |
| [app/generation-preview/page.tsx](file:///workspace/app/generation-preview/page.tsx) | Outline editor + live preview |
| [app/payment-sandbox/page.tsx](file:///workspace/app/payment-sandbox/page.tsx) | Sandbox checkout UI |
| [app/admin/page.tsx](file:///workspace/app/admin/page.tsx) | Admin console (provider config, usage) |
| [app/admin/login/page.tsx](file:///workspace/app/admin/login/page.tsx) | Admin login |
| [app/lab/s2s/[id]/page.tsx](file:///workspace/app/lab/s2s/%5Bid%5D/page.tsx) | S2S lab playground |

### Layouts & error boundaries

- [app/layout.tsx](file:///workspace/app/layout.tsx) — Root layout. Wires `ThemeProvider`, `I18nProvider`, `ServerProvidersInit`, `AccessCodeGuard`, `AuthProvider`, `VisitorTracker`, and the `Toaster`.
- [app/error.tsx](file:///workspace/app/error.tsx), [app/global-error.tsx](file:///workspace/app/global-error.tsx) — Error boundaries.
- [app/globals.css](file:///workspace/app/globals.css) — Tailwind v4 entry, theme variables, utility classes.

### API routes (selected)

See [api-reference.md](./api-reference.md) for the full list. The most important ones:

- `app/api/chat/route.ts` — Stateless LLM chat (SSE)
- `app/api/generate-classroom/route.ts` + `[jobId]/route.ts` — Course generation jobs
- `app/api/generate/{image,video,tts,tts-stream,scene-outlines-stream,scene-content,scene-actions,agent-profiles}/route.ts` — Per-stage content APIs
- `app/api/classroom/route.ts` + `app/api/classroom-media/[classroomId]/[...path]/route.ts` — Classroom CRUD + media proxy
- `app/api/transcription/{route,realtime/route}.ts` — ASR endpoints
- `app/api/omni-realtime/route.ts` — Qwen Omni S2S relay
- `app/api/payments/{catalog,checkout,orders/[orderId],webhooks/[provider],sandbox/complete}/route.ts` — Payments
- `app/api/auth/{login,logout,me,register}/route.ts` — Auth
- `app/api/admin/{route,provider-config,track}/route.ts` — Admin
- `app/api/access-code/{status,verify}/route.ts` — Access gate
- `app/api/verify-{model,image-provider,video-provider,pdf-provider}/route.ts` — Settings verification
- `app/api/web-search/route.ts` — Tavily web search
- `app/api/parse-pdf/route.ts` — PDF parser
- `app/api/server-providers/route.ts` — Server-side provider visibility
- `app/api/azure-voices/route.ts` — Voice list for Azure TTS
- `app/api/pbl/chat/route.ts` — PBL chat
- `app/api/quiz-grade/route.ts` — Quiz grading
- `app/api/proxy-media/route.ts` — Media proxy (SSRF-guarded)
- `app/api/learning/route.ts` — Lesson analytics + dashboard data
- `app/api/health/route.ts` — Health probe
- `app/api/digital-human/zego-token/route.ts` — ZEGO digital human token
- `app/api/generate-classroom/[jobId]/route.ts` — Polling endpoint for job progress

---

## `components/` — React UI

The `components/` directory holds all React components. They are **client components** by default unless a file is explicitly marked. Server-only logic lives in `lib/`.

### `components/ui/`

shadcn-style primitives, lightly customized for Tailwind v4 and Radix. Includes `button`, `card`, `dialog`, `dropdown-menu`, `popover`, `select`, `tabs`, `tooltip`, `command`, `carousel`, `collapsible`, `context-menu`, `input-group`, `sonner`, etc. `flag-icon.tsx` renders a country flag by `countryCode`.

### `components/chat/`

- [chat-area.tsx](file:///workspace/components/chat/chat-area.tsx) — Main chat surface (tabs, list, lecture notes). Exposes a ref API used by `Stage`.
- [chat-session.tsx](file:///workspace/components/chat/chat-session.tsx) — Per-session message list.
- [session-list.tsx](file:///workspace/components/session-list/session-list.tsx) — Left-rail list of saved sessions.
- [process-sse-stream.ts](file:///workspace/components/chat/process-sse-stream.ts) — Parses `text/event-stream` into typed events for `useStageStore`.
- [use-chat-sessions.ts](file:///workspace/components/chat/use-chat-sessions.ts) — CRUD hook for chat sessions.
- [lecture-notes-view.tsx](file:///workspace/components/chat/lecture-notes-view.tsx) — Lecture mode (auto-scroll notes).
- [proactive-card.tsx](file:///workspace/components/chat/proactive-card.tsx), [inline-action-tag.tsx](file:///workspace/components/chat/inline-action-tag.tsx) — Inline UI affordances.
- [chat-area-tab-strategy.ts](file:///workspace/components/chat/chat-area-tab-strategy.ts) — Tab routing rules.
- [chat-feedback-summary-anchor.ts](file:///workspace/components/chat/chat-feedback-summary-anchor.ts), [feedback-packet-metadata.ts](file:///workspace/components/chat/feedback-packet-metadata.ts) — Anchor points and metadata for lightweight feedback cards.

### `components/stage/`

- [stage.tsx](file:///workspace/components/stage.tsx) — Top-level classroom component. Owns the `PlaybackEngine`, drives `ActionEngine`, dispatches `useWsChatSession` events, handles scene rendering, digital human panel, and lesson timer.
- [stage/scene-sidebar.tsx](file:///workspace/components/stage/scene-sidebar.tsx) — Sidebar of scenes.
- [stage/scene-renderer.tsx](file:///workspace/components/stage/scene-renderer.tsx) — Switches between scene type renderers.

### `components/canvas/`

- [canvas-area.tsx](file:///workspace/components/canvas/canvas-area.tsx) — The main editing canvas.
- [canvas-toolbar.tsx](file:///workspace/components/canvas/canvas-toolbar.tsx) — Tool selection.

### `components/scene-renderers/`

- [pbl-renderer.tsx](file:///workspace/components/scene-renderers/pbl-renderer.tsx) — PBL shell.
- [quiz-renderer.tsx](file:///workspace/components/scene-renderers/quiz-renderer.tsx), [quiz-view.tsx](file:///workspace/components/scene-renderers/quiz-view.tsx) — Quiz UI.
- [interactive-renderer.tsx](file:///workspace/components/scene-renderers/interactive-renderer.tsx) — HTML / scientific model interaction.
- [pbl/](file:///workspace/components/scene-renderers/pbl) — PBL sub-components: `role-selection`, `workspace`, `chat-panel`, `issueboard-panel`, `guide`, `learning-lab-shell`, `use-pbl-chat`.

### `components/slide-renderer/`

PPT-style slide editor and live renderer. Mirrors the structure of upstream MAIC-OSS slide editor.

- `Editor/` — `ScreenCanvas`, `ScreenElement`, `HighlightOverlay`, `LaserOverlay`, `SpotlightOverlay`, `ZoomWrapper`, `enlyai-stage-screen`.
- `Editor/Canvas/Operate/` — Per-element interaction (resize, rotate, drag, etc.) and the `Operate` aggregator.
- `Editor/Canvas/hooks/` — Reusable canvas hooks (`useDragElement`, `useScaleElement`, `useRotateElement`, `useSelectElement`, `useMouseSelection`, `useDrop`, …).
- `components/element/` — Renderers for `ChartElement`, `CodeElement`, `ImageElement`, `LatexElement`, `LineElement`, `ShapeElement`, `TableElement`, `TextElement`, `VideoElement`, plus their `hooks/`.
- `components/element/ImageElement/ImageOutline/` — Image clip outlines.
- `components/element/TextElement/ProsemirrorEditor.tsx` — Wraps the local ProseMirror editor in [lib/prosemirror](file:///workspace/lib/prosemirror).
- `components/ThumbnailSlide/` — Thumbnail rendering.

### `components/settings/`

Settings tabs:
- `index.tsx` (enlyai shell) + `enlyai-settings-shell.tsx`
- `general-settings.tsx`, `agent-settings.tsx`, `audio-settings.tsx`, `tts-settings.tsx`, `asr-settings.tsx`
- `image-settings.tsx`, `video-settings.tsx`, `pdf-settings.tsx`, `web-search-settings.tsx`
- `digital-human-settings.tsx`
- `provider-list.tsx`, `provider-config-panel.tsx`, `add-provider-dialog.tsx`, `add-audio-provider-dialog.tsx`
- `model-selector.tsx`, `model-edit-dialog.tsx`
- `utils.ts` (shared)

### `components/ai-elements/`

LLM-UI primitive components: `artifact`, `canvas` (xyflow), `chain-of-thought`, `checkpoint`, `code-block`, `confirmation`, `connection`, `context`, `conversation`, `edge`, `image`, `inline-citation`, `loader`, `message`, `model-selector`, `node`, `open-in-chat`, `panel`, `plan`, `prompt-input`, `queue`, `reasoning`, `shimmer`, `sources`, `suggestion`, `task`, `tool`, `toolbar`, `web-preview`.

### Other top-level components

- [components/auth-provider.tsx](file:///workspace/components/auth-provider.tsx) — React context for the current user.
- [components/access-code-guard.tsx](file:///workspace/components/access-code-guard.tsx), [components/access-code-modal.tsx](file:///workspace/components/access-code-modal.tsx) — Access code gate.
- [components/header.tsx](file:///workspace/components/header.tsx) — App header (auth menu, language, lesson timer, profile).
- [components/lesson-timer.tsx](file:///workspace/components/lesson-timer.tsx) — Lesson countdown / elapsed.
- [components/teacher-card.tsx](file:///workspace/components/teacher-card.tsx), [components/teacher-emotion.tsx](file:///workspace/components/teacher-emotion.tsx) — Teacher rendering and emotion overlays.
- [components/classmate-selector.tsx](file:///workspace/components/classmate-selector.tsx) — Classmate picker.
- [components/language-selector.tsx](file:///workspace/components/language-selector.tsx), [components/language-switcher.tsx](file:///workspace/components/language-switcher.tsx) — Locale switchers.
- [components/server-providers-init.tsx](file:///workspace/components/server-providers-init.tsx) — Hydrates the server-side provider list into the client store on mount.
- [components/visitor-tracker.tsx](file:///workspace/components/visitor-tracker.tsx) — Lightweight visit ping.
- [components/agent/](file:///workspace/components/agent) — Agent bar, avatar, config panel, reveal modal.
- [components/audio/](file:///workspace/components/audio) — `speech-button`, `tts-config-popover`.
- [components/dashboard/learning-loop-section.tsx](file:///workspace/components/dashboard/learning-loop-section.tsx) — "What to do next" card.
- [components/digital-human/digital-human-panel.tsx](file:///workspace/components/digital-human/digital-human-panel.tsx) — ZEGO digital human side panel.
- [components/generation/](file:///workspace/components/generation) — `generation-toolbar`, `generating-progress`, `media-popover`, `outlines-editor`.
- [components/landing/marketing-home-page.tsx](file:///workspace/components/landing/marketing-home-page.tsx) — Marketing site.
- [components/learning/lightweight-feedback-card.tsx](file:///workspace/components/learning/lightweight-feedback-card.tsx) — Per-turn feedback.
- [components/payments/payment-sandbox-client.tsx](file:///workspace/components/payments/payment-sandbox-client.tsx) — Sandbox checkout client.
- [components/roundtable/](file:///workspace/components/roundtable) — Multi-agent roundtable UI (`index.tsx`, `audio-indicator.tsx`, `presentation-speech-overlay.tsx`, `constants.ts`).
- [components/whiteboard/](file:///workspace/components/whiteboard) — Whiteboard (`index.tsx`, `whiteboard-canvas.tsx`, `whiteboard-history.tsx`).
- [components/admin/provider-config-editor.tsx](file:///workspace/components/admin/provider-config-editor.tsx) — Admin editor for `server-providers.yml`.

---

## `lib/` — Domain Logic

`lib/` is the heart of the project. Subdirectories are organized by capability.

### `lib/ai/` — LLM call layer

- [providers.ts](file:///workspace/lib/ai/providers.ts) — `PROVIDERS` registry (model lists, capabilities, base URLs).
- [llm.ts](file:///workspace/lib/ai/llm.ts) — `callLLM`, `streamLLM` (unified facade over the AI SDK).
- [thinking-context.ts](file:///workspace/lib/ai/thinking-context.ts) — `AsyncLocalStorage`-backed thinking budget per request (server-only).

Key exports: `PROVIDERS`, `callLLM`, `streamLLM`, `Output`, `thinkingContext`.

### `lib/audio/` — TTS, ASR, voice

| File | Responsibility |
| --- | --- |
| [types.ts](file:///workspace/lib/audio/types.ts) | `TTSProviderId`, `ASRProviderId`, voice and audio payload types |
| [constants.ts](file:///workspace/lib/audio/constants.ts) | `TTS_PROVIDERS`, `ASR_PROVIDERS` registries (client-safe) |
| [tts-providers.ts](file:///workspace/lib/audio/tts-providers.ts) | `generateTTS()` switch over providers |
| [asr-providers.ts](file:///workspace/lib/audio/asr-providers.ts) | `transcribeAudio()` switch |
| [tts-utils.ts](file:///workspace/lib/audio/tts-utils.ts) | Text chunking, sentence splitting, long-speech helpers |
| [tts-prosody.ts](file:///workspace/lib/audio/tts-prosody.ts) | SSML/markup parsing for TTS prosody |
| [asr-selection.ts](file:///workspace/lib/audio/asr-selection.ts) | Provider + language resolution |
| [asr-fallback.ts](file:///workspace/lib/audio/asr-fallback.ts) | Fallback chain logic |
| [asr-language.ts](file:///workspace/lib/audio/asr-language.ts) | ASR language resolution per lesson |
| [runtime-asr.ts](file:///workspace/lib/audio/runtime-asr.ts) | Runtime ASR availability check |
| [voice-resolver.ts](file:///workspace/lib/audio/voice-resolver.ts) | Voice picking from settings |
| [bailian-realtime.ts](file:///workspace/lib/audio/bailian-realtime.ts) | Qwen realtime TTS + FunASR realtime ASR WebSocket clients |
| [omni-realtime.ts](file:///workspace/lib/audio/omni-realtime.ts) | Qwen Omni S2S session manager |
| [omni-realtime-store.ts](file:///workspace/lib/audio/omni-realtime-store.ts) | State store for Omni sessions |
| [funasr-realtime-session-registry.ts](file:///workspace/lib/audio/funasr-realtime-session-registry.ts) | In-memory session registry |
| [funasr-realtime-session-store.ts](file:///workspace/lib/audio/funasr-realtime-session-store.ts) | Per-session store |
| [funasr-realtime-redis-coordinator.ts](file:///workspace/lib/audio/funasr-realtime-redis-coordinator.ts) | Redis-backed cross-instance coordination |
| [funasr-realtime-metrics.ts](file:///workspace/lib/audio/funasr-realtime-metrics.ts) | Metrics emission |
| [streaming-tts-segmenter.ts](file:///workspace/lib/audio/streaming-tts-segmenter.ts) | Chunks streaming TTS into speakable segments |
| [streaming-audio.ts](file:///workspace/lib/audio/streaming-audio.ts) | Streaming audio utilities |
| [pcm-audio.ts](file:///workspace/lib/audio/pcm-audio.ts) | PCM → WAV conversion |
| [microphone-access.ts](file:///workspace/lib/audio/microphone-access.ts) | Mic permission handling |
| [filler-sounds.ts](file:///workspace/lib/audio/filler-sounds.ts) | Pre-baked filler audio |
| [browser-tts-preview.ts](file:///workspace/lib/audio/browser-tts-preview.ts) | Browser TTS preview |
| [use-tts-preview.ts](file:///workspace/lib/audio/use-tts-preview.ts) | React hook wrapping preview |
| [azure.json](file:///workspace/lib/audio/azure.json) | Static Azure voice list |

### `lib/auth/` — Authentication

- [index.ts](file:///workspace/lib/auth/index.ts) — `verifyToken`, `signSession`, `hashPassword`, `comparePassword`, cookie helpers.
- [access-token.ts](file:///workspace/lib/auth/access-token.ts) — Access code JWT verification.
- [access-code-cookie.ts](file:///workspace/lib/auth/access-code-cookie.ts) — Access code cookie helpers.

### `lib/buffer/` — Stream buffer

- [stream-buffer.ts](file:///workspace/lib/buffer/stream-buffer.ts) — `StreamBuffer` accumulator for streaming UI.

### `lib/chat/`

- [build-chat-store-state.ts](file:///workspace/lib/chat/build-chat-store-state.ts) — Builds the chat store state from server data.
- [action-translations.ts](file:///workspace/lib/chat/action-translations.ts) — i18n mappings for action display.

### `lib/constants/`

- [agent-defaults.ts](file:///workspace/lib/constants/agent-defaults.ts) — Default agent configurations.
- [generation.ts](file:///workspace/lib/constants/generation.ts) — Generation constants (timeouts, retries, etc.).

### `lib/contexts/`

- [scene-context.tsx](file:///workspace/lib/contexts/scene-context.tsx) — Generic `SceneProvider` / `useSceneData` for extensible scene types.
- [media-stage-context.tsx](file:///workspace/lib/contexts/media-stage-context.tsx) — Bridges the media generation state with the stage.

### `lib/db/` — Drizzle / SQLite

- [schema.ts](file:///workspace/lib/db/schema.ts) — All tables (`users`, `sessions`, `learningProgress`, `lessonHistory`, `lessonSessionAnalytics`, `teacherMemories`, `realtimeTranscriptionSessions`, `paymentOrders`, …).
- [index.ts](file:///workspace/lib/db/index.ts) — `getDb()` singleton; runs `CREATE TABLE IF NOT EXISTS` and adds optional columns at boot.

### `lib/digital-human/` — ZEGO integration

- [zego-realtime-client.ts](file:///workspace/lib/digital-human/zego-realtime-client.ts) — Browser-side wrapper around `zego-express-engine-webrtc`.
- [zego-token-schema.ts](file:///workspace/lib/digital-human/zego-token-schema.ts) — Token request/response types.

### `lib/export/`

| File | Responsibility |
| --- | --- |
| [use-export-pptx.ts](file:///workspace/lib/export/use-export-pptx.ts) | PPTX export hook |
| [use-export-classroom.ts](file:///workspace/lib/export/use-export-classroom.ts) | `.maic.zip` export hook |
| [classroom-zip-utils.ts](file:///workspace/lib/export/classroom-zip-utils.ts) | ZIP serialization helpers |
| [classroom-zip-types.ts](file:///workspace/lib/export/classroom-zip-types.ts) | ZIP manifest types |
| [latex-to-omml.ts](file:///workspace/lib/export/latex-to-omml.ts) | LaTeX → OOXML math (uses `packages/mathml2omml`) |
| [svg-path-parser.ts](file:///workspace/lib/export/svg-path-parser.ts) | SVG path parser |
| [svg2base64.ts](file:///workspace/lib/export/svg2base64.ts) | SVG → base64 |
| [svg-arc-to-cubic-bezier.d.ts](file:///workspace/lib/export/svg-arc-to-cubic-bezier.d.ts) | Type shim for the upstream `svg-arc-to-cubic-bezier` package |
| [html-parser/](file:///workspace/lib/export/html-parser) | `format.ts`, `index.ts`, `lexer.ts`, `parser.ts`, `stringify.ts`, `tags.ts`, `types.ts` — minimal HTML AST used by the export pipeline |

### `lib/generation/` — Two-stage generation

| File | Responsibility |
| --- | --- |
| [generation-pipeline.ts](file:///workspace/lib/generation/generation-pipeline.ts) | Barrel re-export of the sub-modules below |
| [pipeline-types.ts](file:///workspace/lib/generation/pipeline-types.ts) | `AgentInfo`, `SceneGenerationContext`, `GenerationResult`, callbacks |
| [prompt-formatters.ts](file:///workspace/lib/generation/prompt-formatters.ts) | Helpers for prompt building |
| [json-repair.ts](file:///workspace/lib/generation/json-repair.ts) | Robust JSON parsing (uses `jsonrepair` + `partial-json`) |
| [outline-generator.ts](file:///workspace/lib/generation/outline-generator.ts) | Stage 1: requirements → scene outlines |
| [scene-generator.ts](file:///workspace/lib/generation/scene-generator.ts) | Stage 2: outlines → full scenes |
| [scene-builder.ts](file:///workspace/lib/generation/scene-builder.ts) | Deterministic builder used as fallback |
| [pipeline-runner.ts](file:///workspace/lib/generation/pipeline-runner.ts) | Orchestrates the two stages and emits progress |
| [action-parser.ts](file:///workspace/lib/generation/action-parser.ts) | Parses the streamed action array into typed actions |
| [interactive-post-processor.ts](file:///workspace/lib/generation/interactive-post-processor.ts) | HTML cleanup for interactive scenes |
| [tts-degradation.ts](file:///workspace/lib/generation/tts-degradation.ts) | Detects when TTS is failing and degrades gracefully |
| [wait-for-student.ts](file:///workspace/lib/generation/wait-for-student.ts) | Detects `wait_for_student` action semantics |
| [lesson-tts.ts](file:///workspace/lib/generation/lesson-tts.ts) | TTS request body builder for prefetch |
| [lesson-language.ts](file:///workspace/lib/generation/lesson-language.ts) | Lesson language directive resolution |
| [prompts/](file:///workspace/lib/generation/prompts) | `loader.ts`, `index.ts`, `types.ts`; templates/ and snippets/ as Markdown |
| `prompts/templates/` | `requirements-to-outlines`, `web-search-query-rewrite`, `slide-content`, `quiz-content`, `slide-actions`, `quiz-actions`, `interactive-html`, `interactive-scientific-model`, `interactive-actions`, `pbl-actions` (system + user each) |
| `prompts/snippets/` | `action-types.md`, `element-types.md`, `json-output-rules.md` |

### `lib/hooks/` — Reusable React hooks

| Hook | Purpose |
| --- | --- |
| [use-theme.tsx](file:///workspace/lib/hooks/use-theme.tsx) | `next-themes` wrapper |
| [use-i18n.tsx](file:///workspace/lib/hooks/use-i18n.tsx) | `react-i18next` wrapper |
| [use-audio-recorder.ts](file:///workspace/lib/hooks/use-audio-recorder.ts) | MediaRecorder wrapper with busy-lock recovery |
| [use-browser-asr.ts](file:///workspace/lib/hooks/use-browser-asr.ts) | Web Speech API ASR |
| [use-browser-tts.ts](file:///workspace/lib/hooks/use-browser-tts.ts) | Web Speech API TTS |
| [use-discussion-tts.ts](file:///workspace/lib/hooks/use-discussion-tts.ts) | Discussion TTS playback |
| [use-ws-audio-recorder.ts](file:///workspace/lib/hooks/use-ws-audio-recorder.ts) | Mic streaming for WS classroom |
| [use-ws-audio-player.ts](file:///workspace/lib/hooks/use-ws-audio-player.ts) | PCM playback for WS classroom |
| [use-ws-chat-session.ts](file:///workspace/lib/hooks/use-ws-chat-session.ts) | WS classroom session hook |
| [use-classroom-websocket.ts](file:///workspace/lib/hooks/use-classroom-websocket.ts) | Reconnect/ping/state for `/ws/classroom` |
| [use-omni-realtime.ts](file:///workspace/lib/hooks/use-omni-realtime.ts) | Qwen Omni S2S client |
| [use-zego-digital-human-stream.ts](file:///workspace/lib/hooks/use-zego-digital-human-stream.ts) | ZEGO stream consumer |
| [use-scene-generator.ts](file:///workspace/lib/hooks/use-scene-generator.ts) | Drives Stage 1+2 from the client (with TTS prefetch) |
| [use-streaming-text.ts](file:///workspace/lib/hooks/use-streaming-text.ts) | StreamBuffer wrapper for text reveal |
| [use-history-snapshot.ts](file:///workspace/lib/hooks/use-history-snapshot.ts) | Undo/redo |
| [use-draft-cache.ts](file:///workspace/lib/hooks/use-draft-cache.ts) | Local draft persistence |
| [use-canvas-operations.ts](file:///workspace/lib/hooks/use-canvas-operations.ts) | Canvas edit operations |
| [use-order-element.ts](file:///workspace/lib/hooks/use-order-element.ts) | Element z-order |
| [use-slide-background-style.ts](file:///workspace/lib/hooks/use-slide-background-style.ts) | Slide background theming |
| [use-lesson-completion.ts](file:///workspace/lib/hooks/use-lesson-completion.ts) | Lesson completion side effects |
| [use-media-query.ts](file:///workspace/lib/hooks/use-media-query.ts) | `matchMedia` wrapper |

### `lib/i18n/`

- [index.ts](file:///workspace/lib/i18n/index.ts), [config.ts](file:///workspace/lib/i18n/config.ts), [resources.ts](file:///workspace/lib/i18n/resources.ts), [locale-detection.ts](file:///workspace/lib/i18n/locale-detection.ts)
- [locales.ts](file:///workspace/lib/i18n/locales.ts) — `supportedLocales` registry.
- [types.ts](file:///workspace/lib/i18n/types.ts) — Type definitions.
- [locales/](file:///workspace/lib/i18n/locales) — `zh-CN.json`, `en-US.json`, `ja-JP.json`, `ru-RU.json`, `ar-SA.json`.
- [TRANSLATION_GUIDE.md](file:///workspace/lib/i18n/TRANSLATION_GUIDE.md) — How to add or update translations.

### `lib/landing/`

- [hero-teacher.ts](file:///workspace/lib/landing/hero-teacher.ts) — Hero data on the landing page.

### `lib/learning/`

| File | Responsibility |
| --- | --- |
| [scene-pacing.ts](file:///workspace/lib/learning/scene-pacing.ts) | `LessonRhythmPhase`, `LESSON_PHASE_BOUNDARIES`, pacing enforcement |
| [active-classroom-engine.ts](file:///workspace/orchestration/active-classroom-engine.ts) | Engine for hard pacing actions (advance / skip / wrap up) |
| [lesson-completion.ts](file:///workspace/lib/learning/lesson-completion.ts) | `LessonProcessSummary`, `LessonReviewSummary` |
| [lesson-duration.ts](file:///workspace/lib/learning/lesson-duration.ts) | Lesson length handling |
| [lesson-process-summary.ts](file:///workspace/lib/learning/lesson-process-summary.ts) | Builds the in-lesson analytics state |
| [lightweight-feedback-card.ts](file:///workspace/lib/learning/lightweight-feedback-card.ts) | Per-turn feedback card model |
| [chat-feedback-summary-anchor.ts](file:///workspace/lib/learning/chat-feedback-summary-anchor.ts) | Anchor for feedback in chat history |
| [cue-user-guidance.ts](file:///workspace/lib/learning/cue-user-guidance.ts) | Cues the user to speak |
| [resume-practice-opening.ts](file:///workspace/lib/learning/resume-practice-opening.ts) | Returning-student opening |
| [student-input.ts](file:///workspace/lib/learning/student-input.ts) | Student input normalization |
| [stage-runtime.ts](file:///workspace/lib/learning/stage-runtime.ts) | Stage runtime state factory (pause / resume / live / …) |
| [dashboard-learning-loop.ts](file:///workspace/lib/learning/dashboard-learning-loop.ts) | "What to do next" computation |
| [dashboard-learning-trend.ts](file:///workspace/lib/learning/dashboard-learning-trend.ts) | Same-language short-term trend |
| [dashboard-next-step.ts](file:///workspace/lib/learning/dashboard-next-step.ts) | Recommended next drill |
| [course-complexity.ts](file:///workspace/lib/learning/course-complexity.ts) | Course complexity levels and helpers |
| [classroom-tab-routing.ts](file:///workspace/lib/learning/classroom-tab-routing.ts) | Tab routing in the classroom |

### `lib/media/`

- [types.ts](file:///workspace/lib/media/types.ts) — `ImageProviderId`, `VideoProviderId`, request types.
- [image-providers.ts](file:///workspace/lib/media/image-providers.ts) — Image provider registry.
- [video-providers.ts](file:///workspace/lib/media/video-providers.ts) — Video provider registry.
- [media-orchestrator.ts](file:///workspace/lib/media/media-orchestrator.ts) — Concurrency-limited fan-out over outlines.
- [adapters/](file:///workspace/lib/media/adapters) — Per-provider HTTP adapters (`grok-image-adapter`, `grok-video-adapter`, `kling-adapter`, `minimax-image-adapter`, `minimax-video-adapter`, `nano-banana-adapter`, `qwen-image-adapter`, `seedance-adapter`, `seedream-adapter`, `veo-adapter`).

### `lib/orchestration/` — Multi-agent LLM orchestration

- [stateless-generate.ts](file:///workspace/lib/orchestration/stateless-generate.ts) — Top-level entry point: single-pass structured generation.
- [director-graph.ts](file:///workspace/lib/orchestration/director-graph.ts) — `LangGraph` `StateGraph` (`START → director → agent_generate → director → END`).
- [director-prompt.ts](file:///workspace/lib/orchestration/director-prompt.ts) — Builds the Director system prompt; parses the decision.
- [ai-sdk-adapter.ts](file:///workspace/lib/orchestration/ai-sdk-adapter.ts) — Bridges `ai` SDK with LangGraph.
- [prompt-builder.ts](file:///workspace/lib/orchestration/prompt-builder.ts) — Builds system prompts and converts messages.
- [tool-schemas.ts](file:///workspace/lib/orchestration/tool-schemas.ts) — Tool schemas for agents.
- [build-next-director-state.ts](file:///workspace/lib/orchestration/build-next-director-state.ts) — Director state transitions.
- [classroom-constraints.ts](file:///workspace/lib/orchestration/classroom-constraints.ts) — Forced turn / discussion end rules.
- [classroom-pace-controller.ts](file:///workspace/lib/orchestration/classroom-pace-controller.ts) — Director-side pacing.
- [active-classroom-engine.ts](file:///workspace/lib/orchestration/active-classroom-engine.ts) — Server-side engine for hard pacing actions.
- [registry/](file:///workspace/lib/orchestration/registry) — `store.ts` (Zustand agent registry) and `types.ts`.

### `lib/payments/`

- [types.ts](file:///workspace/lib/payments/types.ts), [catalog.ts](file:///workspace/lib/payments/catalog.ts) — `PAYMENT_PLANS` and method options.
- [providers.ts](file:///workspace/lib/payments/providers.ts) — Provider checkout functions (WeChat / Alipay / Stripe / PayPal / sandbox).
- [checkout.ts](file:///workspace/lib/payments/checkout.ts) — Checkout flow.
- [config.ts](file:///workspace/lib/payments/config.ts) — Runtime config.
- [store.ts](file:///workspace/lib/payments/store.ts) — DB-backed order store.
- [money.ts](file:///workspace/lib/payments/money.ts) — Currency math.
- [serialization.ts](file:///workspace/lib/payments/serialization.ts) — JSON-safe conversion.

### `lib/pbl/` — Project-Based Learning

- [types.ts](file:///workspace/lib/pbl/types.ts) — `PBLMode`, `PBLAgent`, `PBLIssue`, `PBLIssueboard`.
- [generate-pbl.ts](file:///workspace/lib/pbl/generate-pbl.ts) — PBL generation entry.
- [pbl-system-prompt.ts](file:///workspace/lib/pbl/pbl-system-prompt.ts) — PBL system prompt.
- [mcp/](file:///workspace/lib/pbl/mcp) — MCP-style tools: `agent-mcp`, `agent-templates`, `issueboard-mcp`, `mode-mcp`, `project-mcp`.

### `lib/pdf/`

- [types.ts](file:///workspace/lib/pdf/types.ts) — `PDFProviderId`, `PDFParserConfig`, `ParsedPdfContent`.
- [constants.ts](file:///workspace/lib/pdf/constants.ts) — Provider registry.
- [providers.ts](file:///workspace/lib/pdf/providers.ts) — `parsePDF()` switch.
- [mineru-cloud.ts](file:///workspace/lib/pdf/mineru-cloud.ts) — MinerU v4 cloud API.
- [mineru-parser.ts](file:///workspace/lib/pdf/mineru-parser.ts) — MinerU result extraction.
- [README.md](file:///workspace/lib/pdf/README.md) — Provider notes.

### `lib/playback/`

- [engine.ts](file:///workspace/lib/playback/engine.ts) — `PlaybackEngine` state machine.
- [types.ts](file:///workspace/lib/playback/types.ts) — `EngineMode`, `TopicState`, callbacks.
- [derived-state.ts](file:///workspace/lib/playback/derived-state.ts) — Derived view state.
- [index.ts](file:///workspace/lib/playback/index.ts) — Barrel.

### `lib/prosemirror/` — Local text editor

A minimal ProseMirror build used by the slide text element. Files:
- [index.ts](file:///workspace/lib/prosemirror/index.ts) — `initProsemirrorEditor`.
- [utils.ts](file:///workspace/lib/prosemirror/utils.ts)
- `schema/{index.ts,marks.ts,nodes.ts}` — Document schema.
- `plugins/{index.ts,keymap.ts,inputrules.ts,placeholder.ts}` — Editor plugins.
- `commands/{replaceText.ts,setListStyle.ts,setTextAlign.ts,setTextIndent.ts,toggleList.ts}` — Editor commands.

### `lib/server/` — Server-only utilities

| File | Responsibility |
| --- | --- |
| [api-response.ts](file:///workspace/lib/server/api-response.ts) | `apiError()`, JSON response helpers |
| [provider-config.ts](file:///workspace/lib/server/provider-config.ts) | `server-providers.yml` + env loader, key resolvers |
| [resolve-model.ts](file:///workspace/lib/server/resolve-model.ts) | `resolveModel()` |
| [redis.ts](file:///workspace/lib/server/redis.ts) | `ioredis` singleton |
| [runtime-instance.ts](file:///workspace/lib/server/runtime-instance.ts) | `getRuntimeInstanceId()` |
| [ssrf-guard.ts](file:///workspace/lib/server/ssrf-guard.ts) | URL validation |
| [proxy-fetch.ts](file:///workspace/lib/server/proxy-fetch.ts) | `undici.fetch` wrapper |
| [usage-logger.ts](file:///workspace/lib/server/usage-logger.ts) | LLM/TTS call log |
| [tts-request.ts](file:///workspace/lib/server/tts-request.ts) | Shared TTS request body validation |
| [classroom-websocket.ts](file:///workspace/lib/server/classroom-websocket.ts) | WebSocket handler (PCM + JSON protocol) |
| [classroom-ws-protocol.ts](file:///workspace/lib/server/classroom-ws-protocol.ts) | `ClientMessage` / `ServerMessage` types |
| [classroom-ws-session-store.ts](file:///workspace/lib/server/classroom-ws-session-store.ts) | Per-session state |
| [classroom-generation.ts](file:///workspace/lib/server/classroom-generation.ts) | Server-side course generation entry |
| [classroom-job-runner.ts](file:///workspace/lib/server/classroom-job-runner.ts) | Job runner |
| [classroom-job-store.ts](file:///workspace/lib/server/classroom-job-store.ts) | In-memory + Redis job store |
| [classroom-storage.ts](file:///workspace/lib/server/classroom-storage.ts) | Server-side classroom persistence |
| [classroom-media-generation.ts](file:///workspace/lib/server/classroom-media-generation.ts) | Server-side media generation kickoff |
| [feedback-interceptor.ts](file:///workspace/lib/server/feedback-interceptor.ts) | Detects `CueUser` / `TurnWindowClosed` boundaries |
| [lesson-pace-controller.ts](file:///workspace/lib/server/lesson-pace-controller.ts) | Server-side pacing |
| [lesson-progress-enforcer.ts](file:///workspace/lib/server/lesson-progress-enforcer.ts) | Server-side progress enforcement |
| [barge-in-handler.ts](file:///workspace/lib/server/barge-in-handler.ts) | Detects student interruption |
| [search-query-builder.ts](file:///workspace/lib/server/search-query-builder.ts) | Web search query construction |
| [access-code-cookie.ts](file:///workspace/lib/server/access-code-cookie.ts) | Access code cookie helpers |

### `lib/storage/`

- [index.ts](file:///workspace/lib/storage/index.ts), [types.ts](file:///workspace/lib/storage/types.ts), `providers/noop.ts` — Pluggable object storage (currently `noop`).

### `lib/store/` — Zustand stores

| Store | File |
| --- | --- |
| Stage (course) | [stage.ts](file:///workspace/lib/store/stage.ts) |
| Canvas (edit) | [canvas.ts](file:///workspace/lib/store/canvas.ts) |
| Snapshot (undo/redo) | [snapshot.ts](file:///workspace/lib/store/snapshot.ts) |
| Keyboard | [keyboard.ts](file:///workspace/lib/store/keyboard.ts) |
| Settings (provider/voice/...) | [settings.ts](file:///workspace/lib/store/settings.ts) |
| Settings validation | [settings-validation.ts](file:///workspace/lib/store/settings-validation.ts) |
| Auth (client) | [auth.ts](file:///workspace/lib/store/auth.ts) |
| User memory (returning-student) | [user-memory.ts](file:///workspace/lib/store/user-memory.ts) |
| User profile | [user-profile.ts](file:///workspace/lib/store/user-profile.ts) |
| Media generation jobs | [media-generation.ts](file:///workspace/lib/store/media-generation.ts) |
| Usage tracking | [usage-tracking.ts](file:///workspace/lib/store/usage-tracking.ts) |
| Teacher registry | [teacher-registry.ts](file:///workspace/lib/store/teacher-registry.ts) |
| Whiteboard history | [whiteboard-history.ts](file:///workspace/lib/store/whiteboard-history.ts) |
| Barrel | [index.ts](file:///workspace/lib/store/index.ts) |

### `lib/teacher/`

- [lesson-agent.ts](file:///workspace/lib/teacher/lesson-agent.ts) — `buildPresetLessonTeacherAgent()` constructs the LLM persona.
- [runtime-voice.ts](file:///workspace/lib/teacher/runtime-voice.ts) — Picks the runtime TTS voice per teacher.
- [preview-voice.ts](file:///workspace/lib/teacher/preview-voice.ts) — Preview voice for the settings UI.
- [preferred-voice.ts](file:///workspace/lib/teacher/preferred-voice.ts) — User-preferred voice per teacher.
- [classmate-selection.ts](file:///workspace/lib/teacher/classmate-selection.ts) — Classmate agent assignment.
- [bio-preview.ts](file:///workspace/lib/teacher/bio-preview.ts) — Teacher bio preview rendering.
- [localization.ts](file:///workspace/lib/teacher/localization.ts) — Teacher-specific i18n.

### `lib/types/` — Shared TypeScript types

`action.ts`, `admin-provider-config.ts`, `chat.ts`, `edit.ts`, `export.ts`, `generation.ts`, `pdf.ts`, `provider.ts`, `roundtable.ts`, `settings.ts`, `slides.ts`, `stage.ts`, `teacher.ts`, `web-search.ts`.

### `lib/utils/`

- [cn.ts](file:///workspace/lib/utils/cn.ts) — `clsx + tailwind-merge` class concatenation.
- [create-selectors.ts](file:///workspace/lib/utils/create-selectors.ts) — Selector factory for Zustand.
- [database.ts](file:///workspace/lib/utils/database.ts) — Dexie client database.
- [audio-player.ts](file:///workspace/lib/utils/audio-player.ts) — Audio playback helpers.
- [chat-storage.ts](file:///workspace/lib/utils/chat-storage.ts) — Per-user chat storage.
- [stage-storage.ts](file:///workspace/lib/utils/stage-storage.ts) — Per-user stage storage.
- [playback-storage.ts](file:///workspace/lib/utils/playback-storage.ts) — Playback state persistence.
- [image-storage.ts](file:///workspace/lib/utils/image-storage.ts) — Image mapping persistence.
- [emitter.ts](file:///workspace/lib/utils/emitter.ts) — Tiny pub/sub.
- [geometry.ts](file:///workspace/lib/utils/geometry.ts) — Geometry helpers.
- [element.ts](file:///workspace/lib/utils/element.ts) — Element utility functions.
- [element-fingerprint.ts](file:///workspace/lib/utils/element-fingerprint.ts) — Stable element hashing.
- [model-config.ts](file:///workspace/lib/utils/model-config.ts) — `getCurrentModelConfig()`.
- [index.ts](file:///workspace/lib/utils/index.ts) — Barrel.

### `lib/web-search/`

- [tavily.ts](file:///workspace/lib/web-search/tavily.ts) — `searchWithTavily()`.
- [types.ts](file:///workspace/lib/web-search/types.ts), [constants.ts](file:///workspace/lib/web-search/constants.ts).

### `lib/import/`

- [use-import-classroom.ts](file:///workspace/lib/import/use-import-classroom.ts) — Reverse of the export pipeline. Parses `.maic.zip`, writes media to IndexedDB, hydrates `useStageStore`.

### `lib/logger.ts`

Pinned logger factory. Every domain file calls `createLogger('Name')`.

---

## `packages/` — Local Workspace Packages

- [packages/mathml2omml](file:///workspace/packages/mathml2omml) — Forked LaTeX/MathML → OMML converter used by the PPTX export.
- [packages/pptxgenjs](file:///workspace/packages/pptxgenjs) — Vendored `pptxgenjs` (TypeScript fork) used by `lib/export/use-export-pptx.ts`.

Both are built by `postinstall` (`pnpm install`).

---

## `configs/` — Static Lookup Tables

- `animation.ts`, `chart.ts`, `element.ts`, `font.ts`, `hotkey.ts`, `image-clip.ts`, `latex.ts`, `lines.ts`, `mime.ts`, `shapes.ts`, `storage.ts`, `symbol.ts`, `theme.ts`.

---

## `e2e/` — Playwright Tests

- `fixtures/` — `base.ts`, `auth.ts`, `classroom-seed.ts`, `classroom-voice-harness.ts`, `mock-api.ts`, and `test-data/{scene-actions,scene-content,scene-outlines,settings}.ts`.
- `pages/` — POM: `classroom.page.ts`, `home.page.ts`, `studio.page.ts`, `generation-preview.page.ts`.
- `tests/` — Specs covering classroom interaction, microphone recovery, websocket engine, dashboard report, ASR stress, smoke, happy path, generation flow, home/footer, HTTPS mic, lesson completion persistence, network consistency, and returning-student hydration.

---

## `tests/` — Vitest Unit/Integration Tests

Organized by domain:
- `ai/`, `audio/`, `chat/`, `components/`, `dashboard/`, `deployment/`, `export/`, `generation/`, `i18n/`, `landing/`, `learning/`, `orchestration/`, `payments/`, `server/`, `settings/`, `store/`, `teacher/`, `utils/`.
- `setup-env.ts` — Vitest environment setup.

---

## `scripts/`

| Script | Purpose |
| --- | --- |
| [scripts/start-standalone.mjs](file:///workspace/scripts/start-standalone.mjs) | Copies static assets and runs `custom-server.mjs` |
| [scripts/build-classroom-ws.mjs](file:///workspace/scripts/build-classroom-ws.mjs) | Builds the CJS WebSocket handler |
| [scripts/clean-runtime-artifacts.mjs](file:///workspace/scripts/clean-runtime-artifacts.mjs) | Removes stale runtime files (called by `dev:clean` and `test:e2e:clean`) |
| [scripts/deploy.sh](file:///workspace/scripts/deploy.sh), [scripts/deploy-remote.py](file:///workspace/scripts/deploy-remote.py) | Deployment helpers |
| [scripts/hash-admin-password.mjs](file:///workspace/scripts/hash-admin-password.mjs) | Hashes the admin password for `.env.local` |
| [scripts/probe-enly.mjs](file:///workspace/scripts/probe-enly.mjs) | Diagnostic probe |
| [scripts/simulate-classroom.mjs](file:///workspace/scripts/simulate-classroom.mjs) | Headless classroom simulator |

---

## `docs/`

Project-level documentation, kept in markdown:

- `classroom/` — Improvement plans and P0 follow-ups.
- `deployment/` — `aliyun-standalone-deploy.md`, `github-actions-deploy.md`, `enlyai-migration.md`, `standalone-deploy-pitfalls.md`, `zego-digital-human.md`, `admin-console.md`, `realtime-asr-release-20260509.md`, `domain-diagnosis-20260430.md`.
- `payments/payment-commercialization-backup.md` — Backup plans for payment commercialization.
- `secrets-setup.md` — Required environment secrets.

---

## `types/` — Ambient TypeScript Declarations

- `classroom-e2e.d.ts` — E2E globals.
- `ws.d.ts` — `ws` shims for the browser bundle.

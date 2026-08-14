# EnlyAI Classroom — Code Wiki

> A language-learning focused, AI-powered classroom experience built on Next.js 16, React 19, and the Vercel AI SDK. This wiki is the canonical entry point for understanding, running, and extending the codebase.

This repository is an independently customized application based on an AGPL-3.0 licensed codebase. The product name, docs, classroom flow, voice interaction behavior, and user experience have been rewritten for the EnlyAI learning scenario.

---

## Wiki Index

1. [Architecture](./architecture.md) — High-level system architecture, request lifecycle, and data flow.
2. [Modules](./modules.md) — Per-directory module reference, key classes/functions, and responsibility split.
3. [API Reference](./api-reference.md) — Public HTTP routes, WebSocket protocol, and server-side SDK functions.
4. [Setup & Operations](./setup.md) — Dependencies, environment variables, run / build / test commands, and deployment.

---

## 1. Project at a Glance

| Property | Value |
| --- | --- |
| Product name | EnlyAI Classroom |
| Package name | `enlyai-classroom` |
| Version | `0.1.1` |
| License | AGPL-3.0 |
| Language stack | TypeScript (strict), React 19, Next.js 16.1.2 |
| UI library | Tailwind CSS 4, shadcn/ui (Radix), `@base-ui/react` |
| AI SDK | `ai` (Vercel AI SDK) + `@ai-sdk/*` providers |
| State | Zustand (persisted) + IndexedDB (Dexie) |
| DB | SQLite via Drizzle ORM (`better-sqlite3`) |
| Realtime | Native `ws` + custom `custom-server.mjs` |
| Package manager | pnpm 10.28 |
| Node engine | `>=20.9.0` |
| Build target | Next.js standalone + Docker multi-stage |

---

## 2. Core Capabilities

- **Language-first lesson setup** — choose a target language, virtual teacher, optional classmates, course complexity, and lesson duration.
- **Two-stage course generation** — `requirements → scene outlines → full scenes` (slide / quiz / interactive / PBL).
- **Interactive AI classroom** — multi-agent Director graph, teacher + classmates, real-time discussion, slide elements (text / image / table / chart / line / shape / video / LaTeX), whiteboard.
- **Streaming voice path** — `chat` SSE stream, `/api/generate/tts-stream` (bytes), `/api/generate/tts` (compatibility), browser-native ASR with interim transcripts, full-duplex `ws/classroom` for classroom mode.
- **Learning loop** — post-lesson dashboard, returning-student continuity, lightweight feedback card anchored in chat, recommended next drills.
- **Provider flexibility** — OpenAI, Anthropic, Google Gemini, MiniMax, DeepSeek, GLM, Qwen/DashScope, Doubao, Grok, Ollama, OpenAI-compatible custom providers.
- **Payments** — WeChat Pay / Alipay / Stripe / PayPal / sandbox with region-aware routing and webhooks.
- **Admin console** — provider configuration, usage tracking, teacher registry management.
- **Export & import** — `.maic.zip` round-trip with embedded manifest, PPTX export, HTML activity export, LaTeX → OMML conversion.

---

## 3. Top-Level Repository Layout

```text
enlyai-classroom/
├── app/                    Next.js App Router pages + API routes
│   ├── api/                Server-side HTTP endpoints (chat, classroom, tts, …)
│   ├── classroom/[id]/     Live classroom page (drives <Stage/>)
│   ├── dashboard/          Learning loop dashboard
│   ├── generation-preview/ Outline editor / preview UI
│   ├── studio/             Marketing studio
│   ├── auth/               Login / register page
│   ├── admin/              Admin console
│   ├── layout.tsx          Root layout (Theme, I18n, AccessCode, Auth, Toaster)
│   └── page.tsx            Landing page entry
│
├── components/             React components, grouped by feature
│   ├── ui/                 shadcn-style primitives
│   ├── chat/               Chat panel, session list, SSE processor
│   ├── stage/              Stage sidebar / scene renderer
│   ├── canvas/             Canvas area + toolbar
│   ├── scene-renderers/    Per-scene-type renderers (PBL, Quiz, Interactive)
│   ├── slide-renderer/     Full PPT-style editor (operate, elements, hooks)
│   ├── settings/           Per-feature settings tabs
│   ├── ai-elements/        LLM-UI primitive components
│   ├── audio/              TTS preview, mic button
│   ├── digital-human/      Zego digital human panel
│   ├── generation/         Outline editor, media popover, progress
│   ├── payments/           Payment sandbox client
│   ├── landing/            Marketing home page
│   └── …                   (auth-provider, header, language-selector, …)
│
├── lib/                    Domain logic (TypeScript modules)
│   ├── ai/                 LLM call layer + provider registry
│   ├── audio/              TTS, ASR, real-time, voice resolver
│   ├── auth/               JWT session, access codes
│   ├── chat/               Chat store factory, action translations
│   ├── constants/          Agent defaults, generation constants
│   ├── contexts/           React contexts (scene, media stage)
│   ├── db/                 Drizzle schema + SQLite singleton
│   ├── digital-human/      Zego client + token schema
│   ├── export/             PPTX/HTML/LaTeX exporters + ZIP manifest
│   ├── generation/         Two-stage pipeline, prompts, post-processors
│   ├── hooks/              Reusable React hooks (ASR/TTS/WS/theme/i18n/…)
│   ├── i18n/               5-locale resource loader
│   ├── import/             Classroom ZIP importer
│   ├── landing/            Landing hero data
│   ├── learning/           Scene pacing, lesson completion, dashboard
│   ├── media/              Image / video provider adapters
│   ├── orchestration/      Director graph, stateless generate, tools
│   ├── payments/           Catalog, checkout, providers, store
│   ├── pbl/                Project-Based Learning MCP modules
│   ├── pdf/                MinerU + other PDF providers
│   ├── playback/           Unified playback state machine
│   ├── prosemirror/        Lightweight ProseMirror editor for slide text
│   ├── server/             Server-only utilities (api-response, redis, ws)
│   ├── storage/            Pluggable object storage
│   ├── store/              Zustand stores (stage, settings, auth, …)
│   ├── teacher/            Teacher runtime helpers
│   ├── types/              Shared TypeScript types
│   ├── utils/              Generic utilities (cn, audio-player, database)
│   ├── web-search/         Tavily integration
│   └── logger.ts           Pinned logger factory
│
├── packages/               Local workspace packages
│   ├── mathml2omml/        LaTeX → OOXML math (bundled, see lib/export)
│   └── pptxgenjs/          Vendored fork of pptxgenjs
│
├── e2e/                    Playwright tests
├── tests/                  Vitest unit/integration tests
├── scripts/                Build/deploy/probe helpers
├── configs/                Static config tables (mime, theme, hotkey, …)
├── public/                 Static assets (avatars, logos, flags)
├── docs/                   Project docs (deployment, secrets, plans)
├── custom-server.mjs       Next.js standalone + WebSocket bridge
├── next.config.ts          Next config (transpilePackages, security headers)
├── Dockerfile              Multi-stage Docker build
├── docker-compose.yml      Compose for the enlyai service
├── playwright.config.ts    Playwright config
├── vitest.config.ts        Vitest config
├── eslint.config.mjs       ESLint config
├── pnpm-workspace.yaml     Workspace declaration
└── package.json            Dependencies & scripts
```

---

## 4. Quick Runtime Map

| Surface | Entry point | Notes |
| --- | --- | --- |
| Web UI | [app/page.tsx](file:///workspace/app/page.tsx) → `components/landing/marketing-home-page.tsx` | Marketing landing |
| Live classroom | [app/classroom/[id]/page.tsx](file:///workspace/app/classroom/%5Bid%5D/page.tsx) → [components/stage.tsx](file:///workspace/components/stage.tsx) | Drives playback engine |
| Chat generation | [app/api/chat/route.ts](file:///workspace/app/api/chat/route.ts) → `lib/orchestration/stateless-generate.ts` | SSE stream |
| Full-duplex voice | `ws://…/ws/classroom` → [custom-server.mjs](file:///workspace/custom-server.mjs) → `lib/server/classroom-websocket.ts` | Audio + state |
| Course generation | [app/api/generate-classroom/route.ts](file:///workspace/app/api/generate-classroom/route.ts) → `lib/generation/generation-pipeline.ts` | Two-stage pipeline |
| Dashboard | [app/dashboard/page.tsx](file:///workspace/app/dashboard/page.tsx) | Learning loop |
| Admin | [app/admin/page.tsx](file:///workspace/app/admin/page.tsx) | Provider config, usage |
| Auth | [app/api/auth/*](file:///workspace/app/api/auth) | JWT cookie session |

See [architecture.md](./architecture.md) for the full request lifecycle and [api-reference.md](./api-reference.md) for endpoint details.

---

## 5. Naming and Glossary

| Term | Meaning |
| --- | --- |
| **Stage** | One full course/classroom run; contains many `Scene`s. |
| **Scene** | A single page of the course: `slide` / `quiz` / `interactive` / `pbl`. |
| **Action** | Atomic interaction unit (`speech`, `wb_open`, `spotlight`, `laser`, `discussion`, `scene_next`, …). |
| **Director** | Orchestrator that decides which agent speaks next in the `LangGraph` `StateGraph`. |
| **Agent** | A configured persona (teacher or classmate) with `system_prompt`, voice, and tools. |
| **Classroom Mode** | `teacher_led` / `student_led` / `oral_tutor` (see [lib/types/chat.ts](file:///workspace/lib/types/chat.ts)). |
| **Lesson Rhythm Phase** | `warm_up` → `input` → `guided_practice` → `free_talk` → `wrap_up` (see [lib/learning/scene-pacing.ts](file:///workspace/lib/learning/scene-pacing.ts)). |
| **PBL** | Project-Based Learning scene type with project / agent / issueboard MCPs. |
| **Provider** | External API for LLM, TTS, ASR, image, video, PDF, web-search. |
| **Server Providers** | Server-side YAML/Env configuration shared by all clients (`server-providers.yml`). |

---

## 6. Where to Start Reading

- New to the codebase? Start with [architecture.md](./architecture.md) §"Request Lifecycle".
- Adding a new AI provider? Read [architecture.md](./architecture.md) §"Provider System" and [modules.md](./modules.md) §"`lib/ai`".
- Adding a TTS / ASR provider? Read [modules.md](./modules.md) §"`lib/audio`" and the comments in [lib/audio/types.ts](file:///workspace/lib/audio/types.ts).
- Extending the classroom UI? Read [modules.md](./modules.md) §"`components/stage.tsx`" and `lib/playback/engine.ts`.
- Deploying? Read [setup.md](./setup.md) §"Deployment".

---

## 7. License & Compliance

This project is distributed under AGPL-3.0. If you deploy, modify, or redistribute it, review the license obligations and keep appropriate notices for any inherited third-party or upstream code. This documentation is not legal advice.

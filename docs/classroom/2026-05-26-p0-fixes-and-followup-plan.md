# 2026-05-26 课堂 P0 修复 + 后续规划

## 本次 PR 范围（已完成）

### Bug 1: 进入课堂后 AI 反复播放 "I'm listening, try..." / "Let's keep the speaking rhythm..."

**严重程度**: P0 — 阻塞用户进入课堂正常对话。

**根因**: [`lib/server/lesson-pace-controller.ts`](../../lib/server/lesson-pace-controller.ts) 的 `tick()`
silence 检测在 `else` 分支错误地把 `silenceNotified` 复位为 `false`。

时序：

1. 学生静默 ≥ 5 秒 → `onSilenceTimeout` 触发 → 客户端播放 cue TTS
2. 服务端通过 `notifyTeacherSpeechStarted` 标记 `isTeacherSpeaking = true`
3. tick 进入 `else { silenceNotified = false }` 分支
4. cue 播完 → `notifyTeacherSpeechStopped` → `isTeacherSpeaking = false`
5. 下一秒 tick：`!isStudentSpeaking && !isTeacherSpeaking`，
   `silenceMs` 仍然 ≫ `HARD_SILENCE_THRESHOLD_MS`（因为 `lastStudentActivityAt`
   从未更新过），`silenceNotified` 已被第 3 步清掉 → **立即再次触发同一个 cue**
6. 无限循环

**修复**:

- 移除 `else { silenceNotified = false }` 分支；`silenceNotified` 只在
  `notifyStudentActivity` / `notifyStudentTurnComplete` / phase 转换时复位。
- 触发 `onSilenceTimeout` 后立刻把 `lastStudentActivityAt` 推到 `now`，
  作为对外部误操作的二级保护，保证下一次只可能在又一个完整的静默窗口后才触发。

**回归测试**: 在 [`tests/learning/lesson-pace-controller.test.ts`](../../tests/learning/lesson-pace-controller.test.ts)
新增 2 条用例：

- `does not re-fire silence cue immediately after teacher speech ends`
- `re-arms silence cue only after explicit student activity`

两条用例在修复前**必定失败**（旧逻辑会把单次预期变成 2 次），修复后通过。完整套件 13/13 测试通过。

### Bug 2: 点击下一页 → `Cannot read properties of undefined (reading 'replace')`

**严重程度**: P0 — 阻塞翻页。

**根因**: [`components/slide-renderer/components/element/ProsemirrorEditor.tsx`](../../components/slide-renderer/components/element/ProsemirrorEditor.tsx)
第 88 行 `value.replace(/ style=""/g, '')`。切换到刚挂载的 slide 时，
text element 的 `value` 可能瞬间是 `undefined`（React 重渲染过程中 prop 还没
到位），debounce 的 `handleInput` 一旦在此期间触发就会 throw。

排除路径（已逐一审查）：

- `components/chat/chat-session.tsx` L142 — 进入分支前有 `part.type?.startsWith('action-')` 守卫，安全。
- `lib/orchestration/prompt-builder.ts` L971/L1018 — 同样的守卫，安全。
- `prompt-builder.ts` 中 `stripHtml(html.replace(...))` 等其他位置 — `html` 在调用前已 `|| ''` 兜底。

**修复**: 在 `handleInput` 内将 `value` 包装为 `typeof value === 'string' ? value : ''`，
保持原行为（空字符串与 editor DOM 比较走 update 路径）。

**回归测试**: 该路径在 jsdom 下涉及 ProseMirror EditorView 完整初始化，
单元测试成本高，本次依赖 Playwright E2E 在 follow-up 中补。

### Bug 3: 麦克风点击无效 / ASR 不识别声音

**严重程度**: P0 — 阻塞语音输入。

**状态**: 本次未修复 — 根因需要本地复现确认。

**已排查的代码路径**:

- [`components/roundtable/index.tsx`](../../components/roundtable/index.tsx) `handleToggleVoice` 在
  `isWebSocketVoiceMode = true` 时分支到 `onWebSocketVoiceStart`，否则走 `startRecording`，逻辑清晰。
- L742 disabled 判断: `(!isWebSocketVoiceMode && isTeacherAudioActive) || ...` — WS 模式下
  老师讲话期间按钮**不**禁用，理论上没问题。
- 若 `onWebSocketVoiceStart` 内部 reject（WS 未连接、ASR 会话创建失败、麦克风权限拒绝），
  catch 块会 `setIsVoiceOpen(false)` 并 toast，用户感受到的可能就是「点击无效」。

**最可能的真因（待本地验证）**:

1. WebSocket 未真正建立（`useClassroomWebsocket` 的 readyState 不是 OPEN 时
   `onWebSocketVoiceStart` 拒绝），但 toast 被吞或被 cue 覆盖。
2. 浏览器麦克风权限未授予。
3. ASR realtime session 服务端 token 配置缺失（DashScope `qwen3-tts-flash-realtime` / `fun-asr-realtime`
   需要后端环境变量）。
4. 与 Bug 1 联动：cue 反复触发时 `isTeacherAudioActive = generating` 持续为真，
   非 WS 模式（fallback）下按钮被 disabled。Bug 1 修复后这个症状大概率消失。

**follow-up**: 单独 PR 处理，需要本地复现 + 抓 WS 帧 + 服务端日志。

## 暂未触碰但有把握的范围

### 目标 B（5 项升级）现状盘点

仓库 80% 基础设施已实现，但有 Bug 1 这种关键回归。修复 Bug 1 后，5 项目标的真实差距：

| 目标 | 已有实现 | 差距 |
|------|---------|------|
| 全双工 WS 语音通道 | `lib/server/classroom-websocket.ts`、`lib/hooks/use-ws-chat-session.ts`、`lib/hooks/use-ws-audio-recorder.ts`、`use-ws-audio-player.ts` | 需要端到端延迟实测 ≤ 1.5s |
| 5-phase 状态机 | `LessonPaceController` + `scene-pacing.ts` 已有 `warm_up → input → guided_practice → free_talk → wrap_up` 完整定义和转移 | 缺少老师**主动**发起 phase 启动语的服务端 TTS（目前只发事件给客户端） |
| 流式行内反馈 | `lib/server/feedback-interceptor.ts` 存在 | 需要确认是否真在学生 turn 进行中（不只是结束后）发 `fast_feedback` |
| 硬节奏 | `evaluateLessonPacingEnforcement` 已生成 `advance_scene / skip_topic / start_wrap_up / complete_lesson`；服务端有 `applyEnforcementAction` | 客户端 `onWsSceneAdvance` 监听已接入 `commitSceneSwitch`，链路看起来完整 |
| 智能 barge-in | `lib/server/barge-in-handler.ts` 存在 + `notifyStudentSpeechStarted/Stopped` | 是否保留 turn 上下文做 semantic continuation 需要审查 |

### 推荐的后续 PR 拆分

1. **PR-2**: Bug 3 根因复现 + 修复 + 单元/E2E 测试。
2. **PR-3**: 端到端延迟 + 主动 phase 开场白验证；如果 server side 缺主动 TTS，补 `speakControlPrompt` 调用。
3. **PR-4**: feedback-interceptor 真流式（turn-in-progress）确认 + 必要时改造。
4. **PR-5**: barge-in semantic continuation 审查 + 接力 prompt 构造。
5. **PR-6**: 完整 E2E 验收（5s 主动追问、硬翻页、2s barge-in 响应、15min 自动收尾）。

每个 PR 都应**单独**通过 staging 验证再合并；同时不要把多个 P0 修复打成一个超级 PR，
因为线上回滚粒度会变粗。

## 部署策略

本次仅修代码不做线上部署。建议：

1. 本地完整 `pnpm build` → standalone 上传到 ECS（按 repo memory，
   小内存 ECS 的 Next.js 16 build 易 OOM）。
2. ECS 上灰度 1 个班级验证 24h，确认 Bug 1 不复发。
3. 验证 OK 后再合 main。

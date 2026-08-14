# AI 外教课堂交互改进方案

Last updated: 2026-05-14

## 1. 目标

把当前课堂从“老师主导讲解 + 课后总结很完整”调整成“学生持续开口 + 老师短反馈 + 当场再试 + 课后闭环继续练”的 AI 外教课堂。

最终效果不是让老师说得更像真人，而是让学生在课堂里更像真的在跟真人外教学语言：

1. 先开口，而不是先听一大段说明。
2. 每轮只纠正一个关键点，而不是一次给很多反馈。
3. 纠正后立刻再说一遍，而不是把错误留到课后总结。
4. 下一轮任务要承接上一轮输出，而不是重新开题。
5. 课后建议必须能回流到下次开课入口，而不是只停留在 dashboard 文案。

当前成本约束：不使用 S2S / speech-to-speech realtime 模型作为课堂主链路。体验优化必须基于现有 ASR + TTS + LLM 编排完成：ASR 负责学生输入，LLM 负责短反馈和状态机，TTS 负责老师短句输出。

## 2. 当前实现现状

### 2.1 已经做对的部分

当前仓库已经具备比较好的“课后闭环”基础：

1. 课堂结束后会保存 process analytics、review summary、teacher memory。
2. dashboard 已经能展示 nextStep、learning loop、trend、recent lessons。
3. returning learner 已经能把 teacher memory 注入下一次 chat 请求。
4. orchestration 底层已经具备 student-first、cue_user、retry_after_correction 等能力。
5. 课堂主链路已经具备 ASR/TTS/LLM 的分段式交互基础，不依赖高成本 S2S。

关键文件：

1. app/classroom/[id]/page.tsx
2. components/stage.tsx
3. components/chat/use-chat-sessions.ts
4. lib/orchestration/classroom-constraints.ts
5. lib/learning/lesson-process-summary.ts
6. lib/learning/lesson-completion.ts
7. app/api/learning/route.ts
8. app/dashboard/page.tsx

### 2.2 当前最明显的问题

问题不在“没有学习数据”，而在“课堂中间让学生开口的机制还不够强”。

体感上会出现这些现象：

1. 老师比较容易先解释、先示范、先把内容说完。
2. 学生发言入口存在，但优先级不够高，不像真人老师那样把话筒明确交给学生。
3. 纠错更像点评，而不是把学生立刻拉回 retry。
4. continue-practice 已经能带着上节课 drill 跳进 `/generation-preview`，但还需要继续把这条链路往首轮课堂提示与完整课堂生成里收紧。
5. dashboard 指标已经补上第一层课堂参与度数据，但还不够判断“老师是不是说太多了”“首分钟是否足够快地把学生拉进来”。
6. 生成阶段过去主要靠 prompt 暗示“让学生说”，缺少 scene outline 级别的硬口语任务契约。

## 3. 基于真人外教教学特点的设计原则

下面这些原则应成为课堂产品和 agent 编排的硬约束，而不是可选风格。

### 原则 A: Student Talking Time 要明显高于 Teacher Talking Time

真人口语外教不会把课堂设计成“老师讲、学生听”。课堂的有效性来自学生说得多、说得早、说得连续。

产品含义：

1. 首轮必须优先让学生说。
2. 老师每轮回复必须短。
3. 如果老师已经连续说两轮，系统应主动把轮次切回学生。

### 原则 B: 纠错必须是单点、即时、可重试

真人外教不会一次性纠正发音、语法、表达三个层面。那会打断信心，也会让学生停止表达。

产品含义：

1. 一轮只抓一个问题。
2. 纠错后必须给一个最短正确示范。
3. 示范后立刻要求学生再说一遍。

### 原则 C: 老师的职责是 elicitation，不是 exposition

真人老师更常做的是“问、追问、缩小任务、给句柄、逼出输出”，而不是长篇解释。

产品含义：

1. 老师要多用 prompt、follow-up、choice、sentence frame。
2. 说明类输出必须受 token/句数预算限制。
3. discussion 模式不能天然等于 teacher_demo。

### 原则 D: 课后总结必须回流到下节课的开场任务

真人老师会说：“上次你这个地方容易错，我们先再来一句。”

产品含义：

1. dashboard nextStep 要变成课堂入口参数，而不是只展示在 UI。
2. returning learner openingTopicHint 要直接变成首轮课堂任务。
3. continue-practice 必须把 topic、teacher、focus、drill 带回课堂。

## 4. 当前问题的根因分析

### P0. continue-practice 没有真正闭环到课堂入口

现状：dashboard 按钮现在会写入 resume practice payload，并直接进入 `/generation-preview`。

剩余问题：

1. 续练 drill 已经对用户可见，但还需要继续确保它稳定进入首轮课堂任务，而不只是生成前提示。
2. 产品闭环已经从“课后点评”推进到“续练入口”，但离“老师立刻带着上节课问题开练”还有最后一段提示与课堂编排工作。

### P1. student-first 是底层能力，但不是显性课堂体验

现状：底层 orchestration 支持 cue_user first，但 UI 层没有把“现在轮到你先说”做成高优先级课堂主轴。

后果：

1. 学生容易把课堂理解成看课件、听老师、然后偶尔发言。
2. 课堂氛围不够像口语训练，而更像 AI 在讲内容。

### P2. 纠错链路已经有轻量反馈卡，但 retry 还不是课堂主干

现状：系统能识别 shouldRetry、feedback focus、teacher correction 等信号。

后果：

1. 这些信号更多用在课后总结。
2. 课堂中当场“再说一次”的节奏不够强。

### P3. discussion session 默认 teacher_demo，容易把课堂拖回老师主导

现状：discussion openingMode 默认偏 teacher_demo。

后果：

1. 一旦场景进入 discussion，老师会比较容易长回复。
2. 学生的角色从“主动说”退化成“等老师讲完再接”。

### P4. 指标能衡量错误，不足以衡量课堂主导权

现状：现有 processSummary 更关注 studentRetryCount、teacherCorrectionCount、latency。

后果：

1. 很难判断老师是否说太长。
2. 很难判断第一分钟是否已经把学生拉进开口状态。

## 5. 可落地的分阶段方案

## Phase 0: 确认低成本语音主链路

### 目标

明确当前版本只优化 ASR/TTS/LLM 路径，避免在课堂里误开高成本 S2S。

### 改动内容

1. 前端课堂不再暴露 S2S 启动按钮。
2. settings 里保留旧字段兼容本地缓存，但 `s2sEnabled` 会被强制归零。
3. 后续所有优化围绕 `wait_for_student`、`cue_user`、ASR 自动听写、TTS 短句播放和 LLM 状态机展开。

### 涉及文件

1. components/stage.tsx
2. components/roundtable/index.tsx
3. lib/store/settings.ts

### 验证方式

1. classroom UI 不出现 S2S 控制按钮。
2. 迁移旧设置后 `s2sEnabled` 仍为 false。

## Phase 1: 先把学习闭环和验证补全

### 目标

把 dashboard 从“能显示”提升到“能证明闭环存在”。

### 已完成

1. browser-level dashboard error + retry regression
2. browser-level continue-practice CTA regression
3. full happy path stat-card assertions
4. stable dashboard stat test ids

### 涉及文件

1. app/dashboard/page.tsx
2. e2e/tests/dashboard-learning-report.spec.ts
3. e2e/tests/full-happy-path.spec.ts
4. tests/dashboard/dashboard-page.test.tsx

### 当前价值

这一步不会改善教学法本身，但会让后续课堂改造有稳定回归网。

### Returning learner hydration invariants

为避免 returning learner 的老师记忆在登录边界、慢接口和本地缓存之间串线，当前实现明确依赖以下不变式：

1. 只有存在 teacher agent 的课堂 session 才会尝试解析和注入 `teacherMemory`。
2. `teacherMemory` 的真正来源始终是当前认证用户作用域下的 `useUserMemoryStore`，不是 IndexedDB 里旧 session 的残留配置。
3. chat session 持久化到本地时会主动剥离 `config.teacherMemory`，避免用户切换后把上一位用户的老师记忆从本地恢复回来。
4. hydration 结果只有在 `requestUserId === currentUserId` 且请求序号仍是最新时才会生效，旧请求和竞态返回一律丢弃。
5. 当认证用户变化时，`use-chat-sessions` 会重置 hydration 状态，并清掉所有已缓存 session 上的 `teacherMemory`，然后才为新用户重新拉取 `/api/learning`。
6. 发送课堂请求前会先等待认证状态收敛；对已登录用户，`teacherMemory` hydration 需要完成后才允许进入真正的 teacher-memory 注入路径。
7. returning learner 的 opening personalization 只通过结构化字段进入首轮课堂：`summary`、`openingTopicHint`、`openingFeedbackFocus`，避免把整段非结构化历史直接塞给课堂状态机。
8. 浏览器回归必须覆盖慢 `/api/learning` 场景，证明首个课堂请求仍会携带正确的 `teacherMemory.openingTopicHint` 与 `openingFeedbackFocus`。

对应代码锚点：

1. `components/chat/use-chat-sessions.ts`
2. `lib/utils/chat-storage.ts`
3. `e2e/tests/returning-student-hydration.spec.ts`
4. `tests/chat/use-chat-sessions-auth-guards.test.ts`
5. `tests/store/chat-storage-auth-isolation.test.ts`
6. `tests/store/user-memory-auth-isolation.test.ts`

## Phase 2: 把 continue-practice 从“回首页”升级为“带 drill 的续练入口”

### 当前状态

已完成最小落地版本：dashboard CTA 会写入 `generationSession.lessonConfig.resumePractice`，跳转到 `/generation-preview`，并在生成前直接显示续练目标与聚焦原因。

### 目标

点击 continue-practice 后，学生不需要重新配置，而是直接进入“延续上节课问题”的下一轮练习。

### 改动内容

1. 已新增一个 resume practice payload：
   - teacherId
   - language
   - topic
   - recommendedDrill
   - focusArea
   - focusReason
   - wordsToReview
2. 已让 dashboard CTA 直接跳到 `/generation-preview`，而不是回首页。
3. 已在 generation preview 顶部展示续练目标与聚焦原因，保证生成前可见。
4. 下一步是把这个 payload 再继续压进首轮课堂 opening task，而不只停留在预览与生成配置层。

### 预期效果

1. 课后建议真正进入下一节课。
2. 用户感受到的是“老师接着带我练”，不是“我又回到了起点”。

### 验证方式

1. E2E: dashboard -> continue practice -> studio/classroom
2. 首轮 prompt 必须出现上一课 drill/focus

## Phase 3: 把 student-first 从软规则变成硬状态机

### 目标

确保课堂的默认结构稳定为：

1. 老师给最短场景提示
2. 学生先说
3. 老师短反馈
4. 学生立即 retry
5. 老师再进 follow-up

### 改动内容

1. 在 director graph 里增加更强的 forced student-turn 规则：
   - 首轮必须 cue_user，除非显式 teacher_demo lesson
   - teacher 连续轮次阈值下调
   - correction 后必须先 retry，禁止直接换话题
2. openingMode 细分为：
   - student_first_oral
   - teacher_demo_then_student
   - roleplay_teacher_lead
3. discussion session 不再默认 teacher_demo，而是根据 lesson type 和 student level 决定。
4. 在 scene outline 增加 `speakingContract`：
   - `learnerTask`
   - `targetPhrase`
   - `correctionFocus`
   - `expectedResponseExample`
   - `mustWaitForStudent`
   - `scaffoldLevel`
5. 动作生成阶段把 `speakingContract.mustWaitForStudent` 当作硬规则，最终必须落到 `wait_for_student`，让 ASR 接管学生输入。

### 涉及文件

1. lib/orchestration/director-graph.ts
2. lib/orchestration/classroom-constraints.ts
3. components/chat/use-chat-sessions.ts
4. components/stage.tsx
5. lib/types/generation.ts
6. lib/generation/wait-for-student.ts
7. lib/generation/prompts/templates/requirements-to-outlines/system.md
8. lib/generation/prompts/templates/slide-actions/system.md

### 验证方式

1. server contract tests: first turn cue_user / correction requires retry
2. browser QA: first turn 必须出现 speaking window
3. generation unit test: oral scene with speakingContract must append `wait_for_student`

## Phase 4: 把课堂“开口率”做成一等指标

### 目标

系统不仅知道学生错了什么，还知道老师有没有说太多、学生是否足够早地开口。

### 新增指标建议

1. teacherTurnCount
2. avgTeacherUtteranceLength
3. teacherStudentTurnRatio
4. teacherMonologueMaxChars
5. firstMinuteStudentTurnCount
6. cueAcceptedCount
7. cueIgnoredCount
8. retrySuccessCount

### 应用位置

1. lesson-process-summary
2. lesson completion analytics 存储
3. dashboard learning loop / trend
4. nextStep 生成逻辑

### 预期效果

dashboard 可以明确告诉我们：

1. 学生是否开口太晚
2. 老师是否解释过长
3. 当前阶段最需要的是开口热身、纠错重试，还是表达升级

## Phase 5: 调整 teacher prompt 与 UI 提示，把课堂重心拉回“让学生说”

### 目标

老师说话风格和课堂 UI 一起服务于“逼出输出”。

### Prompt 侧

1. 每轮老师回复设置句数预算。
2. 优先使用 question / choice / sentence frame。
3. 纠错模板固定为：
   - praise briefly
   - point out one issue
   - give one model sentence
   - ask learner to retry now

### UI 侧

1. cue_user 状态时，Roundtable 的 speaking prompt 视觉层级高于 teacher bubble。
2. retry 状态时，输入框默认打开并带一句最短任务提示。
3. 当系统检测 teacher 连续输出过长时，用内部状态切断并回到 student turn。

### 涉及文件

1. lib/teacher/lesson-agent.ts
2. components/roundtable/index.tsx
3. components/stage.tsx
4. lib/learning/student-input.ts

## 6. 本项目的优先实施顺序

### 本周建议

1. 完成 Phase 2：continue-practice 真正带 drill 回课堂
2. 完成 Phase 3 的最小版：首轮强制 cue_user、纠错后强制 retry
3. 补一条 browser E2E：首轮 speaking prompt 必须先于长 teacher explanation 出现

### 下一个迭代建议

1. 新增 teacher-student ratio 指标
2. 重构 discussion openingMode
3. 收紧 teacher prompt token budget

## 7. 最小可落地实施包

如果只做一轮最小改造，建议只做下面 4 项：

1. 去掉课堂 S2S 入口，强制 ASR/TTS/LLM 成为唯一主链路。
2. scene outline 增加 `speakingContract`，让每页口语任务成为结构化数据。
3. action 生成和 fallback 强制 oral scene 以 `wait_for_student` 结束。
4. server-side 强制 oral tutor 首轮 cue_user，correction 后强制 retry。
5. 新增 teacherStudentTurnRatio 和 firstMinuteStudentTurnCount 两个指标。

这样可以在不大规模重构架构的前提下，直接改善“老师讲太多、学生开口太少”的核心问题。

## 8. 验收标准

当下面条件同时成立，说明课堂已经明显更像真人外教口语课：

1. 新用户进入课堂 10 秒内必须被要求开口一次。
2. 每次纠错后，学生必须有一次 retry 机会。
3. continue-practice 能直接带着上一课 drill 开始下一轮。
4. dashboard 能看见 teacher-student turn ratio 和首分钟开口情况。
5. 浏览器 E2E 能证明首轮不是老师长篇讲解，而是 student-first。

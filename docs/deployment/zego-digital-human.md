# ZEGO 数字人部署说明

本文说明 OpenMAIC / EnlyAI 中 ZEGO 数字人实时形象的生产部署方式。当前项目采用“浏览器端 Web SDK + 服务端 token broker”的边界：浏览器只负责加入房间和播放数字人流，服务端 `/api/digital-human/zego-token` 负责认证、授权范围收敛和向自有 token broker 换取 ZEGO token。

## 1. 架构边界

- 浏览器端通过 `zego-express-engine-webrtc` 动态加载 ZEGO Web SDK，避免 SDK 进入 Next.js 服务端 bundle。
- 数字人面板通过 `NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_ROOM_ID` 和 `NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_STREAM_ID` 知道要播放哪个房间和流。
- 浏览器不会直接持有 `ZEGO_SERVER_SECRET`，也不会直接生成 ZEGO token。
- 服务端接口 `/api/digital-human/zego-token` 会先校验当前用户或访问码会话，再向 `ZEGO_TOKEN_SERVER_URL` 请求短期 token。
- 自有 token broker 负责对接 ZEGO 官方服务端 token 生成逻辑，并且只能部署在受控后端环境中。

## 2. 必需环境变量

### 2.1 服务端环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `ZEGO_APP_ID` | 是 | ZEGO 控制台中的应用 ID，必须是正整数。 |
| `ZEGO_SERVER_SECRET` | 是 | 服务端到自有 token broker 的鉴权密钥，只能由密钥管理器或部署平台 Secret 注入，禁止写入前端或仓库。 |
| `ZEGO_TOKEN_SERVER_URL` | 是 | 自有 ZEGO token broker 地址，生产环境必须使用 HTTPS。 |
| `ZEGO_DIGITAL_HUMAN_ROOM_ID` | 是 | 服务端允许签发 token 的数字人房间 ID。 |
| `ZEGO_DIGITAL_HUMAN_STREAM_ID` | 是 | 服务端允许播放的数字人流 ID。 |

### 2.2 浏览器公开环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_ROOM_ID` | 是 | 前端数字人面板请求播放的房间 ID，应与服务端 `ZEGO_DIGITAL_HUMAN_ROOM_ID` 保持一致。 |
| `NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_STREAM_ID` | 是 | 前端数字人面板请求播放的流 ID，应与服务端 `ZEGO_DIGITAL_HUMAN_STREAM_ID` 保持一致。 |
| `NEXT_PUBLIC_ZEGO_SERVER_URL` | 否 | ZEGO Web SDK 连接服务地址，未配置时使用 ZEGO SDK 默认服务。 |

> 注意：公开变量只用于客户端选择房间和流，不具备授权能力。真正的授权范围由服务端 `ZEGO_DIGITAL_HUMAN_ROOM_ID` 和 `ZEGO_DIGITAL_HUMAN_STREAM_ID` 决定。

## 3. 安全要求

1. **HTTPS**：`ZEGO_TOKEN_SERVER_URL` 在生产环境必须是 HTTPS，避免 `ZEGO_SERVER_SECRET` 在明文链路中传输。
2. **SSRF 防护**：服务端会对 `ZEGO_TOKEN_SERVER_URL` 做 SSRF 校验，禁止指向本机、内网、链路本地、保留地址等不可信目标。
3. **禁止重定向**：服务端请求 token broker 时必须保持 `redirect: manual`，避免 broker URL 被 30x 跳转到非预期地址。
4. **room/stream 白名单**：客户端传入的房间和流只能用于匹配服务端白名单；最终用于签发 token 的范围必须来自 `ZEGO_DIGITAL_HUMAN_ROOM_ID` 和 `ZEGO_DIGITAL_HUMAN_STREAM_ID`。
5. **服务端派生 userId**：`userId` 和 `userName` 必须由登录用户或有效访问码会话在服务端派生，不能信任客户端提交值。
6. **固定 TTL**：token 有效期使用服务端固定 TTL，当前为 10 分钟；不要允许客户端自定义更长过期时间。
7. **限流**：`/api/digital-human/zego-token` 按服务端 principal 做基础限流。生产环境建议叠加网关或边缘限流。
8. **Secret 管理**：`ZEGO_SERVER_SECRET` 只能存储在部署平台 Secret、KMS 或后端环境变量中，禁止提交到 git，也不要写入日志。

## 4. token broker 请求约定

当前应用的 Next.js 服务端不会在本仓库中直接实现 ZEGO 官方 token 算法，而是通过 `ZEGO_TOKEN_SERVER_URL` 调用自有 token broker。broker 建议接受以下服务端字段：

- `appId`：来自 `ZEGO_APP_ID`。
- `roomId`：来自服务端 `ZEGO_DIGITAL_HUMAN_ROOM_ID`。
- `streamId`：来自服务端 `ZEGO_DIGITAL_HUMAN_STREAM_ID`。
- `userId`：服务端派生 userId。
- `userName`：服务端派生用户名。
- `ttlSeconds`：服务端固定 TTL。
- `mode`：当前数字人播放模式，可为 `pure-render` 或 `interactive-agent`。

broker 响应建议返回：

- `token`：ZEGO Web SDK 使用的短期 token。
- `expiresAt`：token 过期时间，建议使用 ISO 8601 字符串。

### 4.1 Node.js/Express token broker 示例

下面示例只展示自有 token broker 的边界和校验位置，不包含真实 `ZEGO_SERVER_SECRET` 值，也不替代 ZEGO 官方 token 生成实现。实际部署时应按 ZEGO 当前服务端 SDK 或官方 token 生成文档实现 `generateZegoToken`。

```ts
import express from 'express';
import { z } from 'zod';

const app = express();
app.use(express.json({ limit: '16kb' }));

const brokerRequestSchema = z.object({
   appId: z.number().int().positive(),
   roomId: z.string().min(1).max(128),
   streamId: z.string().min(1).max(128),
   userId: z.string().min(1).max(128),
   userName: z.string().min(1).max(64),
   ttlSeconds: z.number().int().min(60).max(600),
   mode: z.enum(['pure-render', 'interactive-agent']),
});

function assertTrustedBackend(authorizationHeader?: string) {
   const expectedSecret = process.env.ZEGO_SERVER_SECRET;
   if (!expectedSecret || authorizationHeader !== `Bearer ${expectedSecret}`) {
      throw new Error('unauthorized token broker caller');
   }
}

function generateZegoToken(input: z.infer<typeof brokerRequestSchema>) {
   // TODO: 按 ZEGO 官方服务端 SDK / token 文档生成短期 token。
   // 不要把 AppSecret、ServerSecret、token 明文写入日志。
   return { token: 'replace-with-official-zego-token-result', expiresAt: new Date(Date.now() + input.ttlSeconds * 1000).toISOString() };
}

app.post('/internal/zego-token', (req, res) => {
   try {
      assertTrustedBackend(req.header('authorization'));
      const input = brokerRequestSchema.parse(req.body);
      const result = generateZegoToken(input);
      res.json(result);
   } catch {
      res.status(401).json({ error: 'invalid token broker request' });
   }
});

app.get('/health', (_req, res) => {
   res.json({ status: 'ok', service: 'zego-token-broker' });
});

app.listen(process.env.PORT || 3001);
```

生产实现建议继续补充：

- 使用部署平台 Secret 或 KMS 注入 `ZEGO_SERVER_SECRET` 和 ZEGO 官方服务端密钥。
- broker 只暴露给 EnlyAI 后端或内网网关，不直接暴露给浏览器。
- 对 `/internal/zego-token` 做请求体大小限制、IP / mTLS / WAF 限制和结构化审计日志。
- 健康检查只返回 broker 存活状态，不返回 token、secret、roomId 或 streamId。

### 4.2 公版形象与真实端到端验证状态

- **公版形象**：本仓库没有内置 ZEGO 公版形象目录，也不会在代码中固定“公版形象数量”。实际可用公版形象数量取决于 ZEGO 控制台、账号权益、所选数字人产品版本和 ZEGO 当前开放的形象库；部署前需要在 ZEGO 控制台或客户经理提供的配置中确认。
- **真实 ZEGO 端到端测试**：当前已完成本仓库的契约测试、类型检查和生产构建验证；但由于本地没有真实 `ZEGO_APP_ID`、自有 token broker、数字人房间、数字人流和线上形象配置，尚未完成真实 ZEGO 端到端测试。
- **语音同步**：当前代码侧已经为视频流播放和教师发言状态联动预留面板状态，但“数字人形象正常显示并与语音同步”必须在真实 ZEGO 房间中验证，包括口型同步、音画延迟、弱网恢复、浏览器自动播放策略和关闭/重开面板后的流恢复。

## 5. 部署步骤

1. 在 ZEGO 控制台创建应用，确认 `ZEGO_APP_ID` 和服务端 token 生成所需配置。
2. 部署自有 token broker，并确认 broker 仅接受受信后端调用。
3. 在部署平台配置服务端环境变量：
   - `ZEGO_APP_ID`
   - `ZEGO_SERVER_SECRET`
   - `ZEGO_TOKEN_SERVER_URL`
   - `ZEGO_DIGITAL_HUMAN_ROOM_ID`
   - `ZEGO_DIGITAL_HUMAN_STREAM_ID`
4. 在部署平台配置浏览器公开环境变量：
   - `NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_ROOM_ID`
   - `NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_STREAM_ID`
   - `NEXT_PUBLIC_ZEGO_SERVER_URL`
5. 重新构建和发布应用。

## 6. 验证步骤

部署前至少执行：

- `pnpm vitest run tests/deployment/zego-digital-human-deployment.test.ts`
- `pnpm vitest run tests/learning/zego-digital-human-contract.test.ts`
- `pnpm exec tsc --noEmit -p tsconfig.json`
- `pnpm build`

部署后人工验证：

1. 使用有效登录账号或访问码进入课堂。
2. 打开数字人面板，确认 PPT 区域左移，右侧出现数字人区域。
3. 确认数字人区域从预览模式进入 ZEGO 实时流连接状态。
4. 关闭数字人面板，确认 PPT 区域回到居中展示。
5. 在服务端日志确认 `/api/digital-human/zego-token` 没有输出 `ZEGO_SERVER_SECRET` 或 token 明文。
6. 使用错误 room/stream 组合请求 token 接口，应返回拒绝结果，不应签发 token。

### 6.1 真实 ZEGO 端到端测试清单

在具备真实 ZEGO 配置后，至少执行一次完整 E2E：

1. 在 ZEGO 控制台选择公版形象或项目专属形象，记录对应房间和流配置。
2. 启动自有 token broker，确认 `/health` 健康检查返回正常。
3. 登录 EnlyAI，进入课堂并打开数字人面板。
4. 观察浏览器 Network，请求 `/api/digital-human/zego-token` 应返回成功，且响应不包含 `ZEGO_SERVER_SECRET`。
5. 确认 `<video>` 区域显示真实数字人形象，而不是预览头像。
6. 让真实教师或 TTS 发言，检查数字人口型、表情和音频是否语音同步。
7. 连续执行打开、关闭、重新打开数字人面板，确认流释放和重连正常。
8. 使用错误 room/stream 或未登录会话请求接口，确认拒绝签发 token。

## 7. 线上排障和监控

### 7.1 线上排障

- 面板一直停留在预览模式：检查 `NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_ROOM_ID`、`NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_STREAM_ID` 是否在构建时注入，并确认已经重新构建和重新发布。
- `/api/digital-human/zego-token` 返回 401：检查登录态或访问码 cookie 是否有效。
- `/api/digital-human/zego-token` 返回 403：检查 room/stream 白名单是否与浏览器公开变量一致，或 `ZEGO_TOKEN_SERVER_URL` 是否触发 SSRF / HTTPS 校验。
- `/api/digital-human/zego-token` 返回 502：检查自有 token broker 是否可达、是否拒绝请求、是否返回了 token 字段。
- video 没有自动播放：检查浏览器自动播放策略，必要时先静音播放再提示用户交互。
- 数字人有画面但语音不同步：记录浏览器、网络 RTT、ZEGO 房间日志、音频源时间戳和教师发言时间点，优先排查 token broker 延迟、房间推流延迟和 TTS 播放链路。

### 7.2 监控指标

建议采集以下监控指标：

- `/api/digital-human/zego-token` 请求量、成功率、P95 / P99 延迟。
- token broker 请求量、成功率、P95 / P99 延迟。
- 401 / 403 / 429 / 502 响应数量和占比。
- ZEGO token broker 健康检查可用率。
- 数字人面板连接状态：`connecting`、`connected`、`fallback`、`error` 的前端埋点计数。
- 真实 E2E 中音画延迟、首帧时间、断流重连次数。

### 7.3 告警

建议至少配置这些告警：

- `/api/digital-human/zego-token` 5 分钟错误率超过 5%。
- token broker 健康检查连续失败 3 次。
- 429 占比异常升高，提示限流或异常重试。
- `fallback` 状态占比持续升高，提示 ZEGO 配置、token broker 或网络链路异常。
- 日志中出现 `ZEGO_SERVER_SECRET`、token 明文或疑似密钥格式时立即触发安全告警并轮换 secret。

## 8. 回滚方案

- 如果 ZEGO token broker 异常，可先移除或清空 `NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_ROOM_ID` / `NEXT_PUBLIC_ZEGO_DIGITAL_HUMAN_STREAM_ID`，然后重新构建和重新发布应用，前端会回落到数字人预览模式。
- 如果需要完全关闭入口，可在后台或配置中关闭数字人功能开关，课堂仍保持普通 PPT 和教师布局。
- 回滚时不要删除 `ZEGO_SERVER_SECRET` 审计记录；如怀疑泄漏，应立即轮换 secret。

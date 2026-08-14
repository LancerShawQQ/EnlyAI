# EnlyAI 阿里云服务器部署说明

本文档记录本次将 EnlyAI 前端/服务端一体化 Next.js standalone 产物推送并部署到阿里云服务器的真实流程。文档只描述流程与命令，不包含 `.env.local`、API Key、数据库密码、JWT Secret、服务器密码等敏感信息。

## 1. 部署目标

- GitHub 仓库：`git@github.com:LancerXiao/enlyai.git`
- 生产服务器：阿里云 ECS，公网 IP `114.215.183.45`
- 线上服务：`enlyai.service`
- 线上工作目录：`/opt/enlyai/current/.next/standalone`
- Node.js：`/usr/local/bin/node`
- 应用监听：`127.0.0.1:8000`
- 对外访问：Nginx HTTPS 反向代理到本机应用端口

## 2. 整体部署策略

本项目使用 Next.js `standalone` 输出模式。由于生产服务器本地构建成本较高、容易受内存和依赖环境影响，本次采用：

1. 本地完成测试与生产构建。
2. 将 `.next/standalone`、`.next/static`、`public` 打包。
3. 通过 `scp` 上传到服务器 `/tmp/`。
4. 在服务器解包覆盖当前版本。
5. 恢复共享数据目录软链。
6. 重启 `systemd` 服务。
7. 使用本机和公网 HTTP/HTTPS 验证。

## 3. 提交并推送到 GitHub

本地代码验证完成后，先提交并推送到远端仓库，确保线上版本有可追踪的 Git 记录。

```bash
git status --short --branch
git add <本次需要提交的文件>
git commit -m "fix: align lesson language voices and landing brand"
git push
```

本次关键提交：

- `299b018 test: add regressions for lesson and landing fixes`
- `2d06266 fix: align lesson language voices and landing brand`

注意事项：

- `.env.local` 不提交。
- 原始服务器凭据不写入 Git。
- 如存在未跟踪素材文件，需要确认是否作为正式素材入库；本次实际部署使用的是已转换并提交的 WebP 文件。

## 4. 本地验证

部署前先在本地执行回归测试和生产构建。

```bash
pnpm vitest run \
  tests/generation/lesson-language-directive.test.ts \
  tests/generation/lesson-tts.test.ts \
  tests/teacher/runtime-voice-availability.test.ts \
  tests/store/settings-validation.test.ts \
  tests/learning/lesson-duration.test.ts \
  tests/landing/lili-parrot-asset.test.ts

pnpm build
```

本次验证结果：

- 6 个测试文件通过。
- 50 个测试用例通过。
- `pnpm build` 成功。
- Next.js 静态页生成 `41/41` 成功。

后续为麦克风图标按钮补充可访问名称后，又执行过：

```bash
pnpm exec tsc --noEmit -p tsconfig.json
pnpm lint -- components/audio/speech-button.tsx
pnpm vitest run tests/landing/lili-parrot-asset.test.ts
pnpm build
```

结果均通过。

## 5. 构建产物说明

`pnpm build` 后需要部署的目录如下：

- `.next/standalone`：Next.js standalone 运行时与服务端文件。
- `.next/static`：Next.js 静态资源。
- `public`：公开静态资源，例如首页里里图片、logo、头像等。

服务器最终目录结构关键点：

```text
/opt/enlyai/current/.next/standalone/
├── server.js
├── .next/static/
├── public/
└── data -> /opt/enlyai/shared/data
```

其中 `data` 必须是指向共享数据目录的软链，避免部署覆盖运行期 SQLite 数据和上传数据。

## 6. 打包上传

本次先尝试过 `rsync`，但服务器没有安装 `rsync`，报错为服务器端 `rsync: command not found`，因此改用 `tar + scp`。

本地打包命令：

```bash
tar -C .next/standalone -czf /tmp/enlyai-standalone.tgz .
tar -C .next/static -czf /tmp/enlyai-static.tgz .
tar -C public -czf /tmp/enlyai-public.tgz .
```

上传到服务器：

```bash
scp \
  /tmp/enlyai-standalone.tgz \
  /tmp/enlyai-static.tgz \
  /tmp/enlyai-public.tgz \
  root@114.215.183.45:/tmp/
```

本次上传包大小大致为：

- `enlyai-standalone.tgz`：约 165 MB
- `enlyai-static.tgz`：约 5 MB
- `enlyai-public.tgz`：约 2 MB

## 7. 服务器解包与重启

登录服务器后执行部署动作。核心原则是：清理当前 standalone 目录中的旧代码，但保留共享 `data` 目录对应的持久化数据。

```bash
ssh root@114.215.183.45
```

服务器侧部署命令示例：

```bash
set -e
APP_DIR=/opt/enlyai/current/.next/standalone
SHARED_DATA=/opt/enlyai/shared/data

mkdir -p "$APP_DIR"
mkdir -p "$SHARED_DATA"

# 清理旧运行时代码。注意不要删除共享数据源目录。
find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} +

# 解包 standalone。
tar -xzf /tmp/enlyai-standalone.tgz -C "$APP_DIR"

# 解包 Next.js 静态资源。
mkdir -p "$APP_DIR/.next"
tar -xzf /tmp/enlyai-static.tgz -C "$APP_DIR/.next"

# 解包 public 静态资源。
mkdir -p "$APP_DIR/public"
tar -xzf /tmp/enlyai-public.tgz -C "$APP_DIR/public"

# 验证 static 目录层级是否正确。正确结果应当直接出现
# "$APP_DIR/.next/static/chunks"，而不是多一层
# "$APP_DIR/.next/static/static/chunks"。
test -d "$APP_DIR/.next/static/chunks"

# 恢复运行期共享数据软链。
rm -rf "$APP_DIR/data"
ln -sfn "$SHARED_DATA" "$APP_DIR/data"

# 重启服务。
systemctl restart enlyai.service
systemctl status enlyai.service --no-pager
```

本次服务重启后状态：

- `enlyai.service` 为 `active (running)`。
- 主进程为 `/usr/local/bin/node server.js`。

## 8. 线上验证

### 8.1 服务器本机验证

在服务器上验证应用端口和静态资源：

```bash
curl -fsS http://127.0.0.1:8000/api/health
curl -I http://127.0.0.1:8000/avatars/lili-cyber-parrot-full.webp
curl -I http://127.0.0.1:8000/logos/lili-logo.webp
```

本次结果：

- `/api/health` 成功。
- `/avatars/lili-cyber-parrot-full.webp` 返回 `200`。
- `/logos/lili-logo.webp` 返回 `200`。

### 8.2 公网验证

从本地验证公网 HTTPS：

```bash
curl -k -fsS https://114.215.183.45/api/health
curl -k -I https://114.215.183.45/avatars/lili-cyber-parrot-full.webp
```

本次结果：

- `/api/health` 成功。
- 新里里全身图返回 `200`。
- 响应头包含 `Server: nginx/1.20.1`。
- 图片 `Content-Type: image/webp`。

### 8.3 首页敏感词验证

本次还检查首页 HTML 中不再出现底层模型或供应商细节：

```bash
curl -k -fsS https://114.215.183.45/ | grep -E "MiniMax|Speech 2.8|PROVIDER_BADGES|模型在线" || true
```

预期：无输出。

## 9. 浏览器走查

部署后使用 Playwright 对生产地址做了浏览器走查：

- 首页桌面：`1440x1100`
- 首页平板：`768x1000`
- 首页手机：`375x900`
- Studio 桌面：`1440x1000`

走查关注点：

- 首页显示 EnlyAI / 英里AI外教品牌。
- 中文首页 slogan 为“开口即世界”，没有句号。
- 新里里 logo 和全身图已通过 Next 图片优化加载。
- 首页没有 MiniMax、Provider、模型在线、Speech 2.8 等内部实现文案。
- 首页没有可见主题切换入口。
- Studio 有“最后一步”主题输入引导。
- Studio 没有“配置课堂角色”、模型/Provider、设置/主题入口。
- Studio 保留上传 PDF 和麦克风入口。

走查发现并修复的小问题：

- Studio 麦克风图标按钮是纯图标，缺少可访问名称。
- 已在 `SpeechButton` 中增加 `aria-label`，复用现有国际化 tooltip 文案。
- 修复后 TypeScript、Lint、测试、构建均通过。

说明：

- `/api/admin/track` 在无等待场景下可能出现 `net::ERR_ABORTED`，属于页面卸载/埋点请求取消类现象，不影响主页面加载和核心功能。

## 9.1 browser-native ASR 注意事项

- 当服务端没有配置 ASR provider 时，前端默认回退到 `browser-native`。
- 必须通过浏览器信任的 HTTPS 域名访问页面；如果直接使用裸 IP 的 HTTPS 且证书不受信任，麦克风权限和 Web Speech API 都可能失败。
- 阿里云线上验收时，优先使用正式域名，不要把 `https://114.215.183.45` 作为 browser-native ASR 的最终验证入口。

## 9.2 realtime ASR 多实例协调补充

当启用 `/api/transcription/realtime` 的多实例扩容时，必须同时提供 Redis 作为协调层。当前实现中：

- SQLite 继续保存 session metadata 真相源。
- Redis 负责 owner instance heartbeat、跨实例 `append/finish/cancel` 命令转发、结果回传。
- 管理后台通过 `/api/admin?type=realtime` 查看实时错误码分布与 Redis 实例心跳。
- 其中状态码计数是当前实例视图；`sessions` 来自共享 SQLite，`redisInstances` 来自共享 Redis 心跳。

推荐新增环境变量：

```bash
REALTIME_REDIS_URL=redis://127.0.0.1:6379/0
REALTIME_REDIS_HEARTBEAT_INTERVAL_MS=10000
REALTIME_REDIS_HEARTBEAT_TTL_SECONDS=30
REALTIME_REDIS_OPERATION_TIMEOUT_SECONDS=15
REALTIME_REDIS_AUDIO_TTL_SECONDS=60
```

最小上线检查项：

1. 所有应用实例都配置相同的 `REALTIME_REDIS_URL`。
2. `/api/admin?type=realtime` 可返回 `redisInstances`，并看到所有实例 heartbeat。
3. 重点观察 `409`、`413`、`429`、`503` 是否持续增长。
4. Nginx/SLB 不要把这些状态码统一改写成 `200` 或 `500`。

## 9.3 已部署 smoke 与 authenticated smoke 约定

仓库当前存在 `e2e/tests/deployed-commercial-smoke.spec.ts`，用途分为两层：

1. 默认公共 smoke：只覆盖无需登录即可访问的公开页面，例如 `/`、`/auth`、`/admin/login`。
2. 可选 authenticated smoke：通过 `PLAYWRIGHT_SMOKE_ALLOW_AUTH=1` 显式开启，使用预置 smoke 账号登录后访问 `/dashboard`，验证登录态下的基础学习页能够正常打开。

在阿里云线上环境启用 authenticated smoke 之前，必须先确认：

1. 已经准备了专用 smoke 账号，并且该账号不参与正式运营统计或已经有清理策略。
2. 该账号的邮箱和密码通过环境变量安全注入，而不是写死在仓库或脚本里。
3. 该账号登录后的 dashboard 数据量足以稳定渲染基础学习页。

推荐命令示例：

```bash
PLAYWRIGHT_BASE_URL=https://<你的域名或IP> \
PLAYWRIGHT_SKIP_WEBSERVER=1 \
PLAYWRIGHT_IGNORE_HTTPS_ERRORS=1 \
PLAYWRIGHT_SMOKE_ALLOW_AUTH=1 \
PLAYWRIGHT_SMOKE_EMAIL=smoke@example.com \
PLAYWRIGHT_SMOKE_PASSWORD='<smoke-password>' \
pnpm playwright test e2e/tests/deployed-commercial-smoke.spec.ts --project=chromium --reporter=line
```

如果线上环境没有专用 smoke 账号，就不要开启 `PLAYWRIGHT_SMOKE_ALLOW_AUTH=1`，保持公共 smoke 即可。

## 10. 回滚建议

当前部署是直接覆盖当前目录的方式。更稳妥的生产方案可以升级为 release 目录模式：

```text
/opt/enlyai/releases/<timestamp>/
/opt/enlyai/current -> /opt/enlyai/releases/<timestamp>/
/opt/enlyai/shared/data
/opt/enlyai/shared/.env.local
```

推荐后续改造：

1. 每次上传解包到新的 release 目录。
2. 验证新 release 可启动。
3. 原子切换 `/opt/enlyai/current` 软链。
4. 重启服务。
5. 如失败，切回上一个 release 并重启。

## 11. 常见问题

### 11.1 `rsync` 不可用

现象：

```text
bash: rsync: command not found
rsync error code 12
```

处理：

- 安装服务器 `rsync`；或
- 使用本文档的 `tar + scp` 流程。

本次采用第二种方式。

### 11.2 访问域名异常但 IP 正常

如果 `https://114.215.183.45` 正常，但 `https://www.enlyai.com` 出现 403、reset 或 SNI/Host 相关异常，需要优先检查：

- 域名 DNS 是否正确解析到当前 ECS。
- 阿里云安全策略或备案/接入策略。
- Nginx `server_name` 与证书配置。
- HTTPS SNI 配置。

这类问题通常不属于 Next.js 应用代码问题。

### 11.3 数据目录被覆盖

如部署后用户数据丢失或 SQLite 找不到，需要检查：

```bash
ls -l /opt/enlyai/current/.next/standalone/data
```

预期：

```text
data -> /opt/enlyai/shared/data
```

如不是软链，需要重新执行：

```bash
rm -rf /opt/enlyai/current/.next/standalone/data
ln -sfn /opt/enlyai/shared/data /opt/enlyai/current/.next/standalone/data
systemctl restart enlyai.service
```

## 12. ECS 服务器不可清理清单

> **警告**：清理 ECS 服务器时，以下文件和目录绝对不能删除，否则会导致部署失败或数据丢失。

### 12.1 核心部署目录（/opt/enlyai/）

| 文件/目录 | 作用 | 被清理的后果 |
|---|---|---|
| `/opt/enlyai/docker-compose.yml` | Docker Compose 编排文件 | 无法启动容器 |
| `/opt/enlyai/.env` | Docker 镜像地址 + JWT_SECRET（docker compose 变量插值来源） | 容器无法拉取正确镜像，JWT_SECRET 丢失导致用户登录全部失效 |
| `/opt/enlyai/.env.local` | 运行时环境变量（API keys, DATABASE_URL 等） | 应用无法连接数据库、API 密钥丢失 |
| `/opt/enlyai/jwt-secret` | JWT 签名密钥持久化文件 | 用户登录 token 全部失效 |
| `/opt/enlyai/server-providers.yml` | AI 服务商配置 | LLM/TTS/ASR 等服务不可用 |
| `/opt/enlyai/data/` | SQLite 数据库目录 | **所有用户数据丢失** |

### 12.2 Docker 相关

| 资源 | 作用 | 被清理的后果 |
|---|---|---|
| Docker 镜像 `enlyai/enlyai-classroom:latest` | 运行中的容器镜像 | 需要重新拉取/构建（构建耗时 10+ 分钟） |
| Docker Volume `enlyai_enlyai-data` | 持久化数据卷 | **用户数据库丢失** |
| `~/.docker/config.json` | ACR 登录凭证 | ECS 无法拉取私有镜像 |

### 12.3 SSL 证书

| 文件/目录 | 作用 | 被清理的后果 |
|---|---|---|
| `/etc/letsencrypt/live/enlyai.com/` | HTTPS 证书符号链接 | 网站无法通过 HTTPS 访问 |
| `/etc/letsencrypt/archive/enlyai.com/` | 证书存档 | 证书续期失败 |
| `/etc/letsencrypt/renewal/` | 证书自动续期配置 | 证书过期后无法自动续期 |

### 12.4 SSH 配置

| 文件/目录 | 作用 | 被清理的后果 |
|---|---|---|
| `~/.ssh/authorized_keys` | CI/CD 部署用的 SSH 公钥 | GitHub Actions 无法 SSH 到 ECS 部署 |

### 12.5 可安全清理的目录

| 目录 | 说明 |
|---|---|
| `/opt/enlyai.disabled.*` | 旧部署备份，可以安全清理 |
| `/app/enlyai/` | 手动构建的文件目录，CI/CD 不依赖它（CI/CD 用 Docker 镜像） |
| `/app/enlyai-build/` | git clone 的源码目录，可以安全清理 |
| `/tmp/Dockerfile*` | 临时 Dockerfile，可以安全清理 |

### 12.6 快速参考：绝对不能删除

```bash
/opt/enlyai/              # 整个目录（部署核心）
/etc/letsencrypt/         # SSL 证书
~/.ssh/authorized_keys    # CI/CD SSH 访问
~/.docker/config.json     # ACR 登录凭证
# Docker volume: enlyai_enlyai-data  # 用户数据库（用 docker volume ls 查看）
```

## 13. 部署前检查清单

每次部署前建议确认：

- [ ] 本地 `git status` 清晰，只有预期改动。
- [ ] 不提交 `.env.local` 或任何密钥。
- [ ] 关键测试通过。
- [ ] `pnpm build` 通过。
- [ ] 新静态资源已包含在 `public` 打包中。
- [ ] 服务器共享数据目录存在。
- [ ] 部署后容器 `enlyai-enlyai-1` 为 `Up` 且 `healthy`。
- [ ] `/api/health` 通过，`gitSha` 与预期 commit 一致。
- [ ] 关键静态资源返回 `200`。
- [ ] 首页无内部模型/Provider 文案泄露。

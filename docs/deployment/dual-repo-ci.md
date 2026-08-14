# 公私分离 CI/CD 部署说明

> 适用于 **EnlyAI**（私有仓 `LancerXiao/enlyai` + 公有仓 `LancerXiao/enlyai-public-ci`）。
> 本文档是接手工程师了解部署流程的入口。

---

## 1. 架构概览

```
开发者 push → 私有仓 LancerXiao/enlyai (main)
                    │
          ┌─────────┴──────────┐
          │ 双重自动触发机制    │
          │                    │
          │ ① trigger-deploy   │ ② watch-and-deploy
          │   (push 实时触发)   │   (每 5 分钟轮询)
          │   秒级响应          │   最多 5 分钟延迟
          │   需要私有仓额度    │   不依赖私有仓额度
          │   ✅ 额度充足时生效 │   ✅ 始终可用（兜底）
          └─────────┬──────────┘
                    │
                    ▼
            公有仓 LancerXiao/enlyai-public-ci
                    │
                    │ deploy.yml (免费无限额度)
                    │ 1. PAT 拉私有源码
                    │ 2. docker build + push ACR
                    │ 3. SSH 部署到 ECS
                    ▼
            阿里云 ECS 114.215.183.45
            www.enlyai.com
```

| 仓库 | 用途 | Actions 额度 |
|---|---|---|
| `LancerXiao/enlyai`（私有） | 业务源码、PR 门禁 (ci.yml) | 2000 min/月（仅轻量任务） |
| `LancerXiao/enlyai-public-ci`（公有） | 部署流水线 (deploy.yml)、自动轮询 (watch-and-deploy.yml)、ECS 诊断 (diag-ecs.yml) | **无限**（GitHub 公有仓免费） |

---

## 2. 自动部署机制（双重保障）

### 2.1 watch-and-deploy.yml（主用，公有仓轮询）

**完全自动，无需手动操作。** 每 5 分钟自动运行一次：

1. 调用 GitHub API 读取私有仓 `main` 分支最新 commit SHA
2. 与公有仓 Variable `LAST_DEPLOYED_SHA` 对比
3. SHA 相同 → 没有新代码 → 结束（耗时 ~5 秒）
4. SHA 不同 → 有新代码 → 触发 `deploy.yml` → 更新 `LAST_DEPLOYED_SHA`

**优点**：不依赖私有仓 Actions 额度，始终可用。
**缺点**：最多 5 分钟延迟。

### 2.2 trigger-deploy.yml（辅助，私有仓 push 触发）

私有仓 `main` 分支收到 push 时，自动调用 GitHub API 触发公有仓的 `deploy.yml`。

**优点**：秒级响应。
**缺点**：依赖私有仓 Actions 额度。额度耗尽时无法运行。

> 两个机制互不冲突，可以同时存在。额度充足时 trigger 更快（秒级），
> 额度耗尽时 watch 兜底（5 分钟延迟）。每月 1 号额度重置后 trigger 自动恢复。

### 2.3 手动触发（紧急修复 / 回滚）

```bash
# 方式 1：gh CLI（普通构建，使用缓存）
gh workflow run deploy.yml --repo LancerXiao/enlyai-public-ci

# 方式 1a：gh CLI（强制 no-cache 构建，确保最新代码）
gh workflow run deploy.yml --repo LancerXiao/enlyai-public-ci -f no_cache=true

# 方式 2：浏览器
# https://github.com/LancerXiao/enlyai-public-ci/actions
# → Deploy (Public Mirror...) → Run workflow
#   - ref: 留空则部署 main
#   - no_cache: 勾选则强制无缓存构建（推荐在修复 bug 后使用）
```

### 2.4 只跑诊断（不出新版本）

```bash
gh workflow run diag-ecs.yml --repo LancerXiao/enlyai-public-ci
```

---

## 3. 部署流水线详解 (deploy.yml)

公有仓 `deploy.yml` 包含 5 个 job：

| Job | 耗时 | 说明 |
|---|---|---|
| **preflight** | ~30s | 验证 10 个 secrets 是否都已配置 |
| **clone** | ~20s | 用 `PRIVATE_REPO_TOKEN` 浅克隆私有仓源码 |
| **build** | ~3min | Docker 多阶段构建 + push 到阿里云 ACR |
| **deploy** | ~2min | SSH+base64 推送 docker-compose.yml → 12 步部署脚本 |
| **diag** | ~30s | 部署后健康检查 |

### 部署脚本 12 步

| 步骤 | 说明 |
|---|---|
| 0/11 | 清理旧 supervisor (systemd/cron/PID)，保留含 docker-compose.yml 的目录 |
| 1/11 | 验证 docker + compose 插件 |
| 2/11 | 创建部署目录 `/opt/enlyai` |
| 3/11 | 停止占用 8000 端口的容器 |
| 4/11 | 写入 `DOCKER_IMAGE` 到 `.env` |
| 5/11 | 确保 `server-providers.yml` 存在 |
| 6/11 | 验证 `.env.local`（缺失仅警告） |
| 6.5/11 | 确保 `JWT_SECRET` 已设置 |
| 7/11 | 登录 ACR (VPC 端点) |
| 8/11 | 拉取最新镜像 |
| 9/11 | 启动容器 (`docker compose up -d`) |
| 10/11 | 验证 `/api/health` 返回 200 |

---

## 4. Secrets 与 Variables 清单

### 私有仓 Secrets (`LancerXiao/enlyai`)

| 名称 | 用途 | 使用位置 |
|---|---|---|
| `PUBLIC_REPO_TOKEN` | 触发公有仓部署的 PAT | `trigger-deploy.yml` |
| `ACR_USERNAME` | 阿里云 ACR 登录 | 保留（备用） |
| `ACR_PASSWORD` | 阿里云 ACR 密码 | 保留（备用） |
| `ECS_HOST` | ECS 主机地址 | 保留（备用） |
| `ECS_USERNAME` | ECS 用户名 | 保留（备用） |
| `ECS_SSH_KEY` | ECS SSH 私钥 | 保留（备用） |
| `ECS_SSH_PORT` | ECS SSH 端口 | 保留（备用） |
| `TS_CN_DOMAIN` | SSL 域名 | 保留（备用） |
| `TS_CN_CERT` | SSL 证书 | 保留（备用） |
| `TS_CN_KEY` | SSL 私钥 | 保留（备用） |

### 公有仓 Secrets (`LancerXiao/enlyai-public-ci`)

| 名称 | 用途 | 必需 |
|---|---|---|
| `PRIVATE_REPO_TOKEN` | 拉取私有仓源码的 PAT | ✅ |
| `ACR_USERNAME` | 阿里云 ACR 登录 | ✅ |
| `ACR_PASSWORD` | 阿里云 ACR 密码 | ✅ |
| `ECS_HOST` | ECS 主机地址 | ✅ |
| `ECS_USERNAME` | ECS 用户名 | ✅ |
| `ECS_SSH_KEY` | ECS SSH 私钥 | ✅ |
| `ECS_SSH_PORT` | ECS SSH 端口 | ✅ |
| `TS_CN_DOMAIN` | SSL 域名 | ✅ |
| `TS_CN_CERT` | SSL 证书 PEM | ✅ |
| `TS_CN_KEY` | SSL 私钥 PEM | ✅ |

### 公有仓 Variables

| 名称 | 值 | 说明 |
|---|---|---|
| `PRIVATE_REPO` | `LancerXiao/enlyai` | 私有仓全名 |
| `LAST_DEPLOYED_SHA` | `<自动更新>` | watch-and-deploy 记录的最近部署 SHA |

---

## 5. 服务器关键路径

| 路径 | 说明 |
|---|---|
| `/opt/enlyai/` | 部署目录（docker-compose.yml、.env、.env.local） |
| `/opt/enlyai/jwt-secret` | JWT 密钥（自动生成，跨部署保留） |
| `/opt/enlyai/server-providers.yml` | 模型提供商配置 |
| `/opt/enlyai/data/` | SQLite 数据库（Docker named volume） |
| `/etc/nginx/conf.d/enlyai.com.conf` | Nginx 反向代理配置 |
| `/etc/letsencrypt/live/enlyai.com/` | Let's Encrypt SSL 证书 |
| `/root/.ssh/id_ed25519` | CI/CD SSH 密钥（公钥在 authorized_keys） |

---

## 6. 故障排查

### 6.1 自动部署未触发

1. 检查公有仓 `watch-and-deploy.yml` 最近运行：https://github.com/LancerXiao/enlyai-public-ci/actions
2. 如果 watch 正常运行且显示 "No new commits" → SHA 未变化，确认代码已推送到 main
3. 如果 watch 未运行 → 检查 workflow 是否被禁用
4. 如果 trigger-deploy 也未运行 → 私有仓额度可能耗尽（每月 1 号重置）

### 6.2 公有仓 preflight 失败：Missing secret

10 个 secrets 有任意一个空着就失败。到公有仓 Settings → Secrets 补齐。

### 6.3 公有仓 clone 失败：Bad credentials

`PRIVATE_REPO_TOKEN` 失效。生成新 PAT → 更新公有仓 secret。

### 6.4 公有仓 build 失败

常见原因：
- `.npmrc` 等隐藏文件丢失 → 确认 `include-hidden-files: true`
- Dockerfile COPY 的文件不存在 → 检查私有仓对应分支

### 6.4.1 Docker 缓存导致部署代码不是最新（重要！）

**症状**：代码已推送到 main，部署成功完成，但线上行为与旧代码一致（如已修复的 bug 仍然出现）。

**根因**：Docker BuildKit 使用 GHA 缓存（`cache-from: type=gha,scope=deploy-v2`）时，某些层可能使用了旧的缓存，导致最终镜像包含部分旧的构建产物。即使 `pnpm build` 步骤显示为"非缓存"（重新执行），底层依赖安装等步骤可能仍使用了缓存。

**解决方案**：手动触发部署时勾选 `no_cache` 选项，强制完全重新构建：

```bash
# 方式 1：gh CLI
gh workflow run deploy.yml --repo LancerXiao/enlyai-public-ci -f no_cache=true

# 方式 2：浏览器
# https://github.com/LancerXiao/enlyai-public-ci/actions
# → Deploy (Public Mirror...) → Run workflow → 勾选 "Force no-cache Docker build"
```

**注意**：no-cache 构建耗时约 15-20 分钟（普通构建约 5-8 分钟），仅在确认缓存问题时使用。

**预防措施**：
- 修改 `package.json`、`pnpm-lock.yaml`、`Dockerfile` 等影响依赖安装的文件后，建议使用 no-cache 部署
- 如果部署后线上行为异常，首先尝试 no-cache 部署
- 可以在部署后检查 `/api/health` 返回的 `gitSha` 确认版本

### 6.5 deploy 失败：no configuration file

`docker-compose.yml` 未推送到 ECS。检查 SSH 连接和密钥。

### 6.6 网站无法访问

```bash
# SSH 登录 ECS
ssh root@114.215.183.45

# 检查容器状态
docker ps -a --filter "name=enlyai"
docker logs --tail 200 enlyai-enlyai-1

# 检查 Nginx
systemctl status nginx
systemctl start nginx  # 如果没运行

# 检查健康
curl http://127.0.0.1:8000/api/health
```

### 6.7 SSL 证书过期

证书在 `/etc/letsencrypt/live/enlyai.com/`，Let's Encrypt 自动续期。
如果 Nginx 没运行，certbot 的定时任务无法完成续期验证。

---

## 7. PAT 轮换

| PAT | 位置 | 用途 | 过期提醒 |
|---|---|---|---|
| `PRIVATE_REPO_TOKEN` | 公有仓 Secret | 拉私有源码 + watch-and-deploy 轮询 | GitHub 邮件提醒 |
| `PUBLIC_REPO_TOKEN` | 私有仓 Secret | 触发公有仓部署 | GitHub 邮件提醒 |

轮换步骤：
1. GitHub → Settings → Developer settings → Fine-grained tokens → 生成新 token
2. 更新对应仓库的 Secret
3. 删除旧 token

---

## 8. 紧急回滚

```bash
# SSH 到 ECS
ssh root@114.215.183.45
cd /opt/enlyai

# 查看可用镜像
docker images | grep enlyai-classroom

# 回滚到指定版本
export DOCKER_IMAGE=crpi-7lz4jf3purzyjv0i-vpc.cn-hangzhou.personal.cr.aliyuncs.com/enlyai/enlyai-classroom:src-<旧sha>
docker compose up -d
```

---

## 9. 模型提供商配置（重要！）

### 9.1 根因分析：为什么部署后模型配置会丢失

**问题**：每次部署后，所有模型提供商（LLM/TTS/ASR/Image/Video）变为"未配置"状态。

**根因**：deploy.yml 的部署脚本存在以下问题：

1. **Step 0** 将 `/opt/enlyai` 整个目录移至 `/opt/enlyai.disabled.{timestamp}`，其中包含 `.env.local`（含所有模型 API Key）
2. **Step 2** 在 `/app/enlyai` 创建新目录
3. **Step 6** 只在 `.env.local` 不存在时创建最小版本（仅 `NODE_ENV`/`HOSTNAME`/`PORT`），**不保留模型配置**
4. 结果：新部署的 `.env.local` 缺少 `AGNES_*`、`MIMO_*`、`ASR_QWEN_*`、`TTS_*`、`IMAGE_*` 等变量

**修复**（已实施）：deploy.yml Step 6 现在会：
- 从旧目录（包括被移走的 `.disabled.*` 目录）查找旧的 `.env.local`
- 将模型相关环境变量（`AGNES_*`/`MIMO_*`/`TTS_*`/`ASR_*`/`IMAGE_*`/`VIDEO_*`/`PDF_*`/`DEFAULT_MODEL`/`TAVILY_*`）合并到新的 `.env.local`
- 如果找不到旧配置，输出明确警告

### 9.2 当前模型提供商配置

`.env.local` 中的模型配置（位于 ECS `/opt/enlyai/.env.local`）：

| 类别 | 优先 Provider | 环境变量前缀 | API Key 来源 | 备注 |
|------|-------------|------------|------------|------|
| **LLM** | agnes (agnes-2.0-flash) | `AGNES_*` | Agnes AI | 完全免费，OpenAI 兼容 |
| **LLM** | mimo (mimo-v2.5) | `MIMO_*` | 小米 MiMo | OpenAI 兼容，v2.5 支持视觉 |
| **TTS** | mimo-tts (mimo-v2.5-tts) | `TTS_MIMO_*` | 小米 MiMo | OpenAI 兼容 |
| **TTS** | qwen-tts (qwen3-tts-flash-realtime) | `TTS_QWEN_*` | 阿里云百炼 | 流式全双工，多音色 |
| **ASR** | qwen-asr (fun-asr-realtime) | `ASR_QWEN_*` | 阿里云百炼 | 实时识别，中英日等多语种 |
| **Image** | agnes-image (agnes-image-2.1-flash) | `IMAGE_agnes_*` | Agnes AI | 完全免费，**不能传 response_format** |

### 9.3 环境变量前缀映射规则

代码中 `lib/server/provider-config.ts` 定义了环境变量前缀到 provider ID 的映射：

```
LLM:   AGNES_ → agnes,  MIMO_ → mimo,  OPENAI_ → openai,  ...
TTS:   TTS_MIMO_ → mimo-tts,  TTS_QWEN_ → qwen-tts,  TTS_MINIMAX_ → minimax-tts,  ...
ASR:   ASR_QWEN_ → qwen-asr,  ASR_OPENAI_ → openai-whisper
Image: IMAGE_agnes_ → agnes-image,  IMAGE_MINIMAX_ → minimax-image,  ...
Video: VIDEO_MINIMAX_ → minimax-video,  VIDEO_GROK_ → grok-video,  ...
```

**注意**：前缀必须完全匹配代码中的映射！之前使用 `IMAGE_agnes_`（小写 agnes）是正确的，
因为代码中 `IMAGE_ENV_MAP` 的 key 是 `IMAGE_agnes`（小写）。
使用不存在的映射如 `IMAGE_agnes_`（如果代码中没有定义）会导致配置无效。

### 9.4 部署后验证模型配置

每次部署后，**必须**验证模型配置是否保留：

```bash
# 方法 1：检查 API
curl -s https://enlyai.com/api/server-providers | python3 -m json.tool
curl -s https://enlyai.com/api/health

# 预期结果：
# - providers 中应有 agnes 和 mimo
# - tts 中应有 qwen-tts 和 mimo-tts
# - asr 中应有 qwen-asr
# - image 中应有 agnes-image
# - health 中 tts: true, imageGeneration: true

# 方法 2：检查 .env.local
ssh root@114.215.183.45
grep -E '^(AGNES_|MIMO_|TTS_|ASR_|IMAGE_agnes_|DEFAULT_MODEL)' /opt/enlyai/.env.local
```

### 9.5 如果模型配置丢失

运行 fix-env workflow 修复：

```bash
gh workflow run fix-env.yml --repo LancerXiao/enlyai-public-ci
```

或手动修复：

```bash
ssh root@114.215.183.45
cd /opt/enlyai
# 编辑 .env.local，添加模型环境变量（参考 .env.example）
vi .env.local
# 重启容器
docker compose down && docker compose up -d
```

### 9.6 添加新的模型提供商

1. 在 `.env.example` 中添加新的环境变量
2. 在 `lib/server/provider-config.ts` 的对应 `ENV_MAP` 中添加映射
3. 在 ECS 的 `/opt/enlyai/.env.local` 中添加实际的 API Key
4. 重启容器
5. 验证 `/api/server-providers` 返回新的 provider

---

## 10. 相关文档

| 文档 | 位置 |
|---|---|
| 公有仓 SETUP.md | https://github.com/LancerXiao/enlyai-public-ci/blob/main/SETUP.md |
| 公有仓 workflows | https://github.com/LancerXiao/enlyai-public-ci/tree/main/.github/workflows |

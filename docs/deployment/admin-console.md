# EnlyAI 管理员后台部署说明

本文说明管理员后台的登录入口、凭据配置、模型 API Key 管理边界和 ZEGO 配置检查方式。

## 登录入口

- 独立管理员登录链接：`/admin/login`
- 管理后台页面：`/admin`
- 默认建议账号名通过 `ADMIN_USERNAME` 配置；不要在源码里提交真实密码。

## 管理员凭据

生产环境必须使用密码哈希和独立 `JWT_SECRET`：

```bash
ADMIN_USERNAME=Lancer
ADMIN_PASSWORD_HASH=<bcrypt-hash>
JWT_SECRET=<long-random-secret>
```

生成密码哈希：

```bash
pnpm node scripts/hash-admin-password.mjs
```

脚本会交互式读取密码并输出 `ADMIN_PASSWORD_HASH`。不要把明文密码写入仓库、文档、测试或部署日志。

开发环境如果暂未设置 `JWT_SECRET`，管理员 token 会使用开发专用的固定 secret；生产环境不会启用该 fallback，必须显式配置 `JWT_SECRET`。

## 模型 API Key 配置

管理员后台支持直接编辑 `server-providers.yml`。页面不会回传任何已保存的 API Key 明文；密钥输入框留空表示保留服务端当前密钥。

推荐使用以下方式替换或轮换 API Key：

1. 登录 `/admin/login`，进入“模型配置”页，直接保存 `server-providers.yml`。
2. 如果你更偏好部署平台环境变量，也可以继续修改 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`MINIMAX_API_KEY` 等环境变量。
3. 运行时优先级始终是“环境变量 > server-providers.yml”。如果同名环境变量已存在，后台 YAML 不会覆盖它。
4. 保存后刷新后台，确认服务商显示为“已配置”。

如果需要集中管理多套 Key，可使用服务端 `server-providers.yml`；该文件不得提交真实密钥。

DeepSeek V4 的多个子版本可以直接写在对应 provider 的 models 列表中，一行一个 model id，前端会按服务端下发的模型列表展示，不再限制为内置枚举。

图片生成测试阶段可优先尝试 `nano-banana`。仓库内已经接入 Gemini image adapter，适合先验证 PPT 插图链路。

## ZEGO 配置

管理员后台的“ZEGO 配置”只显示以下变量是否已配置：

- `ZEGO_APP_ID` / `NEXT_PUBLIC_ZEGO_APP_ID`
- `ZEGO_TOKEN_SERVER_URL`
- `ZEGO_SERVER_SECRET`
- `ZEGO_ALLOWED_ROOMS`
- `ZEGO_ALLOWED_STREAMS`

其中 `ZEGO_SERVER_SECRET` 必须只保存在服务端环境变量或密钥管理器中，不得返回到客户端。

## 安全检查

- 生产环境必须设置 `ADMIN_PASSWORD_HASH` 和 `JWT_SECRET`。
- 管理员 API 使用 8 小时短期 token。
- 登录失败会按客户端维度限频锁定；当前内存限频适合单实例部署，多实例生产环境建议在网关或 Redis 层增加统一限频。
- 所有模型 Key 和 ZEGO Secret 均只展示配置状态，不展示明文。
# 🚀 一键提取 ECS 上的所有部署凭证（最简方案）

你的 ECS 上之前已经登录过阿里云 ACR，并且跑过 nginx，所有凭证都已经躺在服务器里了。下面这 5 步会把**全部 9 个 GitHub Secrets 需要的值**一次性抓出来。

---

## 步骤 1：登录 ECS（仅此 1 次需要密码）

在你自己电脑的终端执行（Mac 终端 / Windows PowerShell）：

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@114.215.183.45
```

会提示输入密码，粘贴：`!freeworkLVooJo2`（输入时不会显示，粘贴后回车即可）

看到 `[root@你的ECS ~]#` 这样的提示符就说明登录成功了。

---

## 步骤 2：读取 ACR 凭证（4 个单条命令，依次执行）

**命令 A — 查看 docker 登录缓存文件：**

```bash
sudo cat /root/.docker/config.json
```

**把输出截图发给我。** 这会告诉我 ACR 凭证是不是缓存了，以及 ACR 的地址。

> 如果文件不存在或没看到 `aliyuncs.com` 相关的条目，说明 ECS 上没有缓存 ACR 凭证，你需要走「步骤 6：去阿里云控制台拿」。

---

## 步骤 3：定位 SSL 证书（1 条命令）

**命令 B — 找 enlyai.com 的证书文件：**

```bash
sudo find / -type f \( -name "fullchain.pem" -o -name "*.crt" -o -name "*.pem" \) 2>/dev/null | grep -v node_modules | grep -E "nginx|ssl|cert" | head -20
```

**把输出截图发给我。** 这会列出服务器上所有可能存放 enlyai.com 证书的路径。

> 看到路径后告诉我，我会告诉你：
> - 哪个是证书文件（用于 `TS_CN_CERT`）
> - 哪个是私钥文件（用于 `TS_CN_KEY`）

---

## 步骤 4：查看 nginx 配置确认证书路径（1 条命令）

**命令 C — 看 nginx 怎么配的：**

```bash
sudo grep -rE "ssl_certificate|listen 443" /etc/nginx/ 2>/dev/null | head -20
```

**把输出截图发给我。** 这一步是为了双保险确认证书文件位置。

---

## 步骤 5：生成 SSH 密钥对（用于 ECS_SSH_KEY）

执行完步骤 2-4 后，**退出 ECS**：

```bash
exit
```

回到你电脑本地终端，执行下面 3 条命令：

**命令 D — 生成 SSH 密钥：**

```bash
ssh-keygen -t ed25519 -C "github-actions-enlyai-deploy" -f ~/.ssh/enlyai-deploy -N ""
```

**命令 E — 查看并复制私钥**（整段复制到 `ECS_SSH_KEY`）：

```bash
cat ~/.ssh/enlyai-deploy
```

**命令 F — 上传公钥到 ECS**（会再问一次密码，粘贴 `!freeworkLVooJo2` 回车）：

```bash
ssh-copy-id -i ~/.ssh/enlyai-deploy.pub root@114.215.183.45
```

看到 "Number of key(s) added: 1" 就成功。

---

## 步骤 6：填到 GitHub

打开 https://github.com/LancerXiao/enlyai/settings/secrets/actions，依次点 "New repository secret"，按下面表格填（9 个 Name 严格按这个大写）：

| Name（严格按这个填） | Secret 的值从哪里来 |
|---|---|
| `ECS_HOST` | 直接填 `114.215.183.45` |
| `ECS_USERNAME` | 直接填 `root` |
| `ECS_SSH_PORT` | 直接填 `22` |
| `TS_CN_DOMAIN` | 直接填 `www.enlyai.com` |
| `ACR_USERNAME` | 步骤 2 命令 A 的输出中我帮你解析出来的用户名 |
| `ACR_PASSWORD` | 步骤 2 命令 A 的输出中我帮你解析出来的密码 |
| `ECS_SSH_KEY` | 步骤 5 命令 E 的整段输出 |
| `TS_CN_CERT` | 我在步骤 3/4 帮你确认路径后给的 cat 命令输出 |
| `TS_CN_KEY` | 我在步骤 3/4 帮你确认路径后给的 cat 命令输出 |

填完后**截图发给我**核对。

---

## 兜底：如果 ECS 上没有 ACR 凭证缓存

万一你的 ECS 是新机器或者 docker 没登录过 ACR，命令 A 会看不到 `aliyuncs.com` 条目。**这种情况下我会让你去阿里云控制台拿**：

1. 浏览器打开：https://cr.console.aliyun.com/
2. 登录你的阿里云账号（和 ECS 同一个）
3. 左侧菜单 → 「访问凭证」或「个人访问凭证」
4. 看到 "Registry 用户名" 类似的字段
5. **点「设置 Registry 密码」/「重置密码」** — 阿里云要求自己设一个密码，记住它
6. 把用户名（一般是你阿里云账号的 UID 数字）和密码告诉我

> 💡 提示：阿里云 ACR 个人版第一次访问会让你"开通服务"，跟着提示点 1 分钟搞定，全部免费。

---

## 关键点

- **每一步都只执行单条命令**，避免粘贴 heredoc 多行脚本出错
- **每一步都截图发给我**，我帮你确认拿到的东西对不对
- **GitHub Secrets 加密存储**，粘贴证书私钥/SSH 私钥都安全
- 整个流程 15-20 分钟

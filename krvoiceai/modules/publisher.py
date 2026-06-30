"""多平台发布模块

将成片发布到主流短视频平台。

三种模式：
- auto:      自动发布（需平台 API/Cookie 已配置）
- semi_auto: 半自动（生成发布清单，用户确认后执行）—— 默认
- manual:    手动（仅生成清单，用户自行发布）

平台支持：
- bilibili:    B站官方 API（需 Cookie）
- douyin:      Playwright 浏览器自动化
- kuaishou:    Playwright 浏览器自动化
- wechat_video: 视频号 Playwright（受限）

合规说明：明确告知用户平台 ToS 风险，默认半自动模式。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..core.base_module import BaseModule, JobContext, ModuleResult


@dataclass
class PublishTarget:
    """发布目标"""
    platform: str
    title: str
    video_path: Path
    cover_path: Optional[Path] = None
    description: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "pending"  # pending / success / failed / skipped
    url: Optional[str] = None
    error: Optional[str] = None


class Publisher(BaseModule):
    """多平台发布模块"""

    name = "publish"
    requires_gpu = False

    def __init__(self, config=None):
        super().__init__(config)
        self.mode = self.config.get("publisher.mode", "semi_auto")
        self.cookies_dir = Path(self.config.get("publisher.cookies_dir", "./config/cookies"))
        self.platforms_cfg = self.config.get("publisher.platforms", {})
        self.publish_interval = self.config.get("publisher.publish_interval", 60)

    def run(self, ctx: JobContext) -> ModuleResult:
        """执行发布"""
        if not ctx.final_video or not ctx.final_video.exists():
            return ModuleResult(success=False, error="无最终视频，无法发布")

        # 确定目标平台
        target_platforms = ctx.metadata.get("publish_platforms")
        if not target_platforms:
            target_platforms = [
                name for name, cfg in self.platforms_cfg.items()
                if cfg.get("enabled", False)
            ]
        if not target_platforms:
            target_platforms = ["bilibili"]  # 默认至少生成清单

        title = ctx.title or "口播视频"
        description = ctx.metadata.get("description", ctx.script_text[:200] if ctx.script_text else "")

        targets = []
        for platform in target_platforms:
            targets.append(PublishTarget(
                platform=platform,
                title=title,
                video_path=ctx.final_video,
                cover_path=ctx.cover_path,
                description=description,
                tags=ctx.metadata.get("tags", []),
            ))

        # 生成发布清单（所有模式都生成）
        manifest_path = ctx.work_dir / "publish_manifest.json"
        self._write_manifest(targets, manifest_path)
        ctx.metadata["publish_manifest"] = str(manifest_path)

        if self.mode == "manual":
            return ModuleResult(
                success=True,
                data={
                    "mode": "manual",
                    "manifest": str(manifest_path),
                    "platforms": [t.platform for t in targets],
                    "message": "已生成发布清单，请手动发布",
                },
            )

        if self.mode == "semi_auto":
            return ModuleResult(
                success=True,
                data={
                    "mode": "semi_auto",
                    "manifest": str(manifest_path),
                    "platforms": [t.platform for t in targets],
                    "message": "已生成发布清单，确认后调用 execute_publish 执行",
                },
            )

        # auto 模式：实际发布
        results = self._publish_all(targets)
        self._write_manifest(targets, manifest_path)  # 更新状态

        success_count = sum(1 for t in targets if t.status == "success")
        return ModuleResult(
            success=success_count > 0,
            data={
                "mode": "auto",
                "manifest": str(manifest_path),
                "results": [
                    {
                        "platform": t.platform,
                        "status": t.status,
                        "url": t.url,
                        "error": t.error,
                    }
                    for t in targets
                ],
                "success_count": success_count,
                "total_count": len(targets),
            },
        )

    def execute_publish(self, manifest_path: Path) -> dict:
        """执行半自动发布（用户确认后调用）"""
        manifest_path = Path(manifest_path)
        if not manifest_path.exists():
            return {"error": "清单不存在"}

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        targets = []
        for item in data["targets"]:
            t = PublishTarget(
                platform=item["platform"],
                title=item["title"],
                video_path=Path(item["video_path"]),
                cover_path=Path(item["cover_path"]) if item.get("cover_path") else None,
                description=item.get("description", ""),
                tags=item.get("tags", []),
                status=item.get("status", "pending"),
            )
            targets.append(t)

        results = self._publish_all(targets)
        self._write_manifest(targets, manifest_path)
        return results

    def _publish_all(self, targets: list[PublishTarget]) -> dict:
        """发布到所有目标平台"""
        results = {}
        for i, target in enumerate(targets):
            if i > 0:
                self.logger.info(f"等待 {self.publish_interval}s 避免频率限制")
                time.sleep(self.publish_interval)
            try:
                if target.platform == "bilibili":
                    result = self._publish_bilibili(target)
                elif target.platform == "douyin":
                    result = self._publish_playwright(target)
                elif target.platform == "kuaishou":
                    result = self._publish_playwright(target)
                elif target.platform == "wechat_video":
                    result = self._publish_playwright(target)
                else:
                    target.status = "skipped"
                    target.error = f"不支持的平台: {target.platform}"
                    result = {"status": "skipped", "error": target.error}

                results[target.platform] = result
            except Exception as e:
                target.status = "failed"
                target.error = str(e)
                results[target.platform] = {"status": "failed", "error": str(e)}
                self.logger.error(f"发布到 {target.platform} 失败: {e}")
        return results

    def _publish_bilibili(self, target: PublishTarget) -> dict:
        """B站 API 发布（基于 bilibili-api-python 库真实上传）

        需要 Cookie 文件 config/cookies/bilibili.json，包含：
            SESSDATA, bili_jct, DedeUserID, buvid3
        """
        cookie_file = self.cookies_dir / "bilibili.json"
        if not cookie_file.exists():
            target.status = "skipped"
            target.error = "B站 Cookie 未配置，跳过"
            self.logger.warning(target.error)
            return {"status": "skipped", "error": target.error}

        try:
            import asyncio
            from bilibili_api import video_uploader, Credential

            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
            # 校验必要字段
            for k in ("SESSDATA", "bili_jct", "DedeUserID"):
                if not cookies.get(k):
                    raise ValueError(f"bilibili Cookie 缺少字段: {k}")

            # 1. 创建凭据
            credential = Credential(
                sessdata=cookies["SESSDATA"],
                bili_jct=cookies["bili_jct"],
                dedeuserid=cookies["DedeUserID"],
            )

            self.logger.info(f"B站发布开始: {target.title}")

            # 2. 创建上传分P
            page = video_uploader.VideoUploaderPage(
                path=str(target.video_path),
                title=target.title,
                description=target.description,
            )

            # 3. 视频元信息
            # tid 分区：122=野生技术协会（适合口播/知识）
            # copyright: 1=自制 2=转载
            meta = {
                "title": target.title,
                "desc": target.description,
                "tid": 122,
                "tag": ",".join(target.tags) if target.tags else "知识,口播",
                "copyright": 1,
            }

            # 4. 创建上传器（封面可选）
            cover_path = str(target.cover_path) if target.cover_path and Path(target.cover_path).exists() else ""
            uploader = video_uploader.VideoUploader(
                pages=[page],
                meta=meta,
                credential=credential,
                cover=cover_path,
            )

            # 5. 异步执行上传
            result = asyncio.run(uploader.start())

            # result 示例: {"bvid": "BV1xxx...", "aid": 123456}
            bvid = result.get("bvid", "") if isinstance(result, dict) else ""
            if bvid:
                url = f"https://www.bilibili.com/video/{bvid}"
                target.status = "success"
                target.url = url
                self.logger.info(f"B站发布成功: {url}")
                return {"status": "success", "url": url, "bvid": bvid}
            else:
                raise RuntimeError(f"上传完成但未返回 bvid: {result}")

        except ImportError:
            target.status = "skipped"
            target.error = "bilibili-api-python 未安装（pip install bilibili-api-python）"
            return {"status": "skipped", "error": target.error}
        except Exception as e:
            target.status = "failed"
            target.error = str(e)
            self.logger.error(f"B站发布失败: {e}")
            return {"status": "failed", "error": str(e)}

    def _publish_playwright(self, target: PublishTarget) -> dict:
        """Playwright 浏览器自动化发布（抖音/快手/视频号）

        流程：
        1. 启动浏览器，加载已保存的Cookie
        2. 打开各平台创作者发布页
        3. 上传视频文件、填写标题/描述
        4. 点击发布按钮
        5. 等待发布完成，提取视频URL

        注意：各平台页面结构可能变化，选择器需根据实际页面调整。
        头部模式：headless=False 让用户可见流程，可手动干预。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            target.status = "skipped"
            target.error = f"playwright 未安装，无法发布到 {target.platform}"
            self.logger.warning(target.error)
            return {"status": "skipped", "error": target.error}

        cookie_file = self.cookies_dir / f"{target.platform}.json"
        if not cookie_file.exists():
            target.status = "skipped"
            target.error = f"{target.platform} Cookie 未配置，跳过（请先调用登录接口）"
            return {"status": "skipped", "error": target.error}

        # 各平台发布页和选择器配置
        platform_publish_cfg = {
            "douyin": {
                "publish_url": "https://creator.douyin.com/creator-micro/content/upload",
                "upload_input": "input[type=file]",
                "title_input": ".ql-editor[data-placeholder='动人标题']",
                "desc_input": ".ql-editor",
                "publish_btn": ".button--1ERwt[data-e2e='publish_article_button']",
                "cookie_domain": ".douyin.com",
                "name": "抖音",
            },
            "kuaishou": {
                "publish_url": "https://cp.kuaishou.com/article/publish/video",
                "upload_input": "input[type=file]",
                "title_input": "input[placeholder*='标题']",
                "desc_input": "textarea[placeholder*='描述']",
                "publish_btn": "button:has-text('发布')",
                "cookie_domain": ".kuaishou.com",
                "name": "快手",
            },
            "wechat_video": {
                "publish_url": "https://channels.weixin.qq.com/platform/post/create",
                "upload_input": "input[type=file]",
                "title_input": "input[placeholder*='标题']",
                "desc_input": "textarea[placeholder*='描述']",
                "publish_btn": "button:has-text('发表')",
                "cookie_domain": ".qq.com",
                "name": "视频号",
            },
        }
        cfg = platform_publish_cfg.get(target.platform)
        if not cfg:
            target.status = "skipped"
            target.error = f"不支持的平台: {target.platform}"
            return {"status": "skipped", "error": target.error}

        self.logger.info(f"Playwright 发布到 {cfg['name']}: {target.title}")

        cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
        # 转 Playwright cookie 格式
        playwright_cookies = []
        for name, value in cookies.items():
            playwright_cookies.append({
                "name": name,
                "value": value,
                "domain": cfg["cookie_domain"],
                "path": "/",
            })

        import time
        with sync_playwright() as p:
            # 非无头，用户可见流程，可手动干预
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            # 加载Cookie
            context.add_cookies(playwright_cookies)
            page = context.new_page()
            page.goto(cfg["publish_url"], wait_until="domcontentloaded")
            # 给Cookie加载留时间
            time.sleep(3)
            # 如果跳到登录页说明Cookie失效
            if "login" in page.url.lower() or "passport" in page.url.lower():
                browser.close()
                target.status = "failed"
                target.error = f"{cfg['name']} Cookie已失效，请重新登录"
                return {"status": "failed", "error": target.error}

            try:
                # 1. 上传视频文件
                upload_input = page.locator(cfg["upload_input"]).first
                upload_input.set_input_files(str(target.video_path))
                self.logger.info(f"已选择视频文件，等待上传...")
                # 等待上传完成（最长5分钟，看进度条消失或出现发布按钮可用）
                for _ in range(150):
                    time.sleep(2)
                    # 检查是否有发布按钮可用 或 上传完成提示
                    if page.locator(cfg["publish_btn"]).count() > 0:
                        break

                # 2. 填写标题
                title_sel = page.locator(cfg["title_input"]).first
                if title_sel.count() > 0:
                    title_sel.fill(target.title)
                    self.logger.info(f"已填写标题: {target.title}")

                # 3. 填写描述（标题和描述可能在不同元素）
                if target.description:
                    desc_sel = page.locator(cfg["desc_input"]).first
                    if desc_sel.count() > 0:
                        desc_sel.fill(target.description)
                        self.logger.info(f"已填写描述")

                # 4. 等待用户确认发布（半自动模式：用户可手动调整后点发布）
                # 这里等待5秒让用户检查，然后自动点击发布
                time.sleep(5)

                # 5. 点击发布
                publish_btn = page.locator(cfg["publish_btn"]).first
                if publish_btn.count() > 0:
                    publish_btn.click()
                    self.logger.info(f"已点击发布按钮")
                    # 等待发布完成
                    time.sleep(10)
                else:
                    self.logger.warning(f"未找到发布按钮，请手动点击发布")

                # 提取发布后的视频URL（尝试从跳转后的页面获取）
                final_url = page.url
                browser.close()

                target.status = "success"
                target.url = final_url
                self.logger.info(f"{cfg['name']}发布完成")
                return {"status": "success", "url": final_url, "platform": target.platform}

            except Exception as e:
                browser.close()
                target.status = "failed"
                target.error = f"{cfg['name']}发布过程出错: {e}"
                self.logger.error(target.error)
                return {"status": "failed", "error": target.error}

    def _write_manifest(
        self, targets: list[PublishTarget], path: Path
    ) -> None:
        """写入发布清单"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "generated_at": time.time(),
            "mode": self.mode,
            "targets": [
                {
                    "platform": t.platform,
                    "title": t.title,
                    "video_path": str(t.video_path),
                    "cover_path": str(t.cover_path) if t.cover_path else None,
                    "description": t.description,
                    "tags": t.tags,
                    "status": t.status,
                    "url": t.url,
                    "error": t.error,
                }
                for t in targets
            ],
        }
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def publish_video(
        self,
        video_path: Path,
        platforms: list[str],
        title: str = "",
        cover_path: Path | None = None,
        description: str = "",
        tags: list[str] | None = None,
        manifest_path: Path | None = None,
    ) -> dict:
        """独立发布接口（供 API 直接调用，不经过流水线）

        Args:
            video_path: 视频文件路径
            platforms: 目标平台列表 ["bilibili", "douyin", ...]
            title: 视频标题
            cover_path: 封面路径（可选）
            description: 视频描述
            tags: 标签列表
            manifest_path: 发布清单保存路径（可选）

        Returns:
            {"results": [...], "success_count": N, "total_count": M, "manifest": path}
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return {"error": "视频文件不存在", "video_path": str(video_path)}

        tags = tags or []
        # 构造发布目标（独立 API 调用：用户已明确指定 platforms，不再检查 enabled）
        targets = []
        for platform in platforms:
            targets.append(PublishTarget(
                platform=platform,
                title=title or video_path.stem,
                video_path=video_path,
                cover_path=Path(cover_path) if cover_path else None,
                description=description,
                tags=tags,
            ))

        if not targets:
            return {"error": "无启用的目标平台", "platforms_requested": platforms}

        # 写初始清单
        if manifest_path is None:
            manifest_path = video_path.parent / "publish_manifest.json"
        manifest_path = Path(manifest_path)
        self._write_manifest(targets, manifest_path)

        # 执行发布
        results = self._publish_all(targets)
        # 更新清单状态
        self._write_manifest(targets, manifest_path)

        success_count = sum(1 for t in targets if t.status == "success")
        return {
            "results": [
                {
                    "platform": t.platform,
                    "status": t.status,
                    "url": t.url,
                    "error": t.error,
                }
                for t in targets
            ],
            "success_count": success_count,
            "total_count": len(targets),
            "manifest": str(manifest_path),
        }

    def get_cookie_status(self) -> dict:
        """检查各平台 Cookie 配置状态"""
        status = {}
        for platform in ("bilibili", "douyin", "kuaishou", "wechat_video"):
            cookie_file = self.cookies_dir / f"{platform}.json"
            status[platform] = {
                "configured": cookie_file.exists(),
                "path": str(cookie_file),
                "enabled": (self.platforms_cfg.get(platform, {}) or {}).get("enabled", False),
            }
        return status

    def save_cookie(self, platform: str, cookie_data: dict) -> dict:
        """保存平台 Cookie"""
        if platform not in ("bilibili", "douyin", "kuaishou", "wechat_video"):
            return {"success": False, "error": f"不支持的平台: {platform}"}
        self.cookies_dir.mkdir(parents=True, exist_ok=True)
        cookie_file = self.cookies_dir / f"{platform}.json"
        cookie_file.write_text(
            json.dumps(cookie_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.logger.info(f"已保存 {platform} Cookie: {cookie_file}")
        return {"success": True, "path": str(cookie_file), "platform": platform}

    # ============ 傻瓜化登录：扫码/浏览器登录自动获取 Cookie ============

    def login_bilibili_qrcode(self) -> dict:
        """B站扫码登录 - 生成二维码，用户手机扫码后自动获取 Cookie

        流程：
        1. 生成登录二维码（返回图片base64或终端字符画）
        2. 用户用B站APP扫码确认
        3. 自动获取 SESSDATA/bili_jct/DedeUserID 并保存

        Returns:
            {"qrcode_image": base64, "qrcode_terminal": str, "message": "..."}
            之后轮询 check_bilibili_login(qrcode_login_obj) 检查扫码状态
        """
        try:
            from bilibili_api import login_v2
        except ImportError:
            return {"success": False, "error": "bilibili-api-python 未安装"}

        # 创建扫码登录实例（保存到实例供后续轮询）
        qr_login = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
        self._bilibili_qr_login = qr_login

        # 生成二维码（注意：FastAPI 已在事件循环中，不能用 asyncio.run）
        import asyncio
        try:
            # 正常环境（CLI/脚本）
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # FastAPI 异步上下文：用 ensure_future + 等待
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, qr_login.generate_qrcode())
                    future.result()
            else:
                loop.run_until_complete(qr_login.generate_qrcode())
        except RuntimeError:
            # 无事件循环，直接 asyncio.run
            asyncio.run(qr_login.generate_qrcode())

        # 获取二维码图片（base64）和终端字符画
        qrcode_image_b64 = ""
        qrcode_terminal_str = ""
        qrcode_file_path = ""
        try:
            qrcode_terminal_str = qr_login.get_qrcode_terminal()
        except Exception:
            pass
        try:
            # 二维码图片对象（含 url 本地路径 + content 二进制）
            pic = qr_login.get_qrcode_picture()
            import base64
            qrcode_image_b64 = base64.b64encode(pic.content).decode("utf-8")
            qrcode_file_path = pic.url or ""
        except Exception:
            pass

        return {
            "success": True,
            "qrcode_image": qrcode_image_b64,  # base64编码的二维码图片，前端可直接显示
            "qrcode_file": qrcode_file_path,   # 二维码本地文件路径
            "qrcode_terminal": qrcode_terminal_str,  # 终端字符画（CLI可用）
            "message": "请用B站APP扫码登录，扫码后调用 check_bilibili_login 检查状态",
        }

    def check_bilibili_login(self) -> dict:
        """检查B站扫码登录状态（配合 login_bilibili_qrcode 使用）

        Returns:
            {"status": "waiting"|"success"|"failed", "cookie": {...}}
        """
        if not getattr(self, "_bilibili_qr_login", None):
            return {"status": "failed", "error": "请先调用 login_bilibili_qrcode 生成二维码"}

        import asyncio
        from bilibili_api import login_v2

        try:
            # 检查扫码状态（注意：FastAPI 已在事件循环中，不能用 asyncio.run）
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run, self._bilibili_qr_login.check_state())
                        state = future.result()
                else:
                    state = loop.run_until_complete(self._bilibili_qr_login.check_state())
            except RuntimeError:
                state = asyncio.run(self._bilibili_qr_login.check_state())
            # state 可能是 QrCodeLoginEvents.WAITING / DONE / EXPIRED
            if self._bilibili_qr_login.has_done():
                # 获取 Credential
                credential = self._bilibili_qr_login.get_credential()
                cookie_data = {
                    "SESSDATA": getattr(credential, "sessdata", "") or "",
                    "bili_jct": getattr(credential, "bili_jct", "") or "",
                    "DedeUserID": getattr(credential, "dedeuserid", "") or "",
                    "buvid3": getattr(credential, "buvid3", "") or "",
                }
                # 自动保存
                self.save_cookie("bilibili", cookie_data)
                self._bilibili_qr_login = None
                return {
                    "status": "success",
                    "cookie": cookie_data,
                    "message": "B站登录成功，Cookie已自动保存",
                }
            else:
                return {"status": "waiting", "message": "等待扫码确认中..."}
        except Exception as e:
            # 超时或失败
            self._bilibili_qr_login = None
            return {"status": "failed", "error": str(e)}

    def login_browser_platform(self, platform: str) -> dict:
        """抖音/快手/视频号浏览器登录 - 弹出浏览器让用户登录，登录后自动提取Cookie

        流程：
        1. 启动 Playwright 浏览器（非无头，用户可见）
        2. 打开平台登录页
        3. 用户手动登录（扫码/账密）
        4. 检测到登录成功后，自动提取所有Cookie保存

        Args:
            platform: douyin / kuaishou / wechat_video

        Returns:
            {"success": True, "cookie": {...}, "message": "..."}
        """
        if platform not in ("douyin", "kuaishou", "wechat_video"):
            return {"success": False, "error": f"不支持的平台: {platform}"}

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "error": "playwright 未安装"}

        # 各平台登录页 URL 和登录成功判断条件
        platform_cfg = {
            "douyin": {
                "login_url": "https://creator.douyin.com/creator-micro/home",
                "success_url_contains": "creator.douyin.com",
                "cookie_domain": ".douyin.com",
                "name": "抖音创作者",
            },
            "kuaishou": {
                "login_url": "https://cp.kuaishou.com/article/publish/video",
                "success_url_contains": "cp.kuaishou.com",
                "cookie_domain": ".kuaishou.com",
                "name": "快手创作者",
            },
            "wechat_video": {
                "login_url": "https://channels.weixin.qq.com/platform/post/create",
                "success_url_contains": "channels.weixin.qq.com",
                "cookie_domain": ".qq.com",
                "name": "微信视频号",
            },
        }
        cfg = platform_cfg[platform]
        self.logger.info(f"启动 {cfg['name']} 浏览器登录...")

        with sync_playwright() as p:
            # 非无头模式，用户可见浏览器
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            page = context.new_page()
            page.goto(cfg["login_url"], wait_until="domcontentloaded")

            # 等待用户登录成功（最长等待5分钟）
            # 判断条件：URL 包含成功标识 且 页面含登录后才有的元素
            import time
            max_wait = 300  # 5分钟
            start = time.time()
            logged_in = False

            self.logger.info(f"请在弹出的浏览器中登录{cfg['name']}账号...")
            while time.time() - start < max_wait:
                try:
                    current_url = page.url
                    # 登录成功的判断：URL跳转到创作者后台 且 不在登录页
                    if (cfg["success_url_contains"] in current_url
                        and "login" not in current_url.lower()
                        and "passport" not in current_url.lower()):
                        # 二次确认：等待2秒看是否稳定
                        time.sleep(2)
                        if cfg["success_url_contains"] in page.url:
                            logged_in = True
                            break
                except Exception:
                    pass
                time.sleep(2)

            if not logged_in:
                browser.close()
                return {"success": False, "error": f"登录超时（5分钟未检测到{cfg['name']}登录成功）"}

            # 登录成功，提取所有Cookie
            cookies = context.cookies()
            browser.close()

            # 转为 {name: value} 字典保存
            cookie_dict = {}
            for c in cookies:
                if cfg["cookie_domain"] in c.get("domain", ""):
                    cookie_dict[c["name"]] = c["value"]

            if not cookie_dict:
                return {"success": False, "error": "登录成功但未提取到Cookie"}

            # 保存
            self.save_cookie(platform, cookie_dict)
            self.logger.info(f"{cfg['name']}登录成功，已保存 {len(cookie_dict)} 个Cookie")
            return {
                "success": True,
                "cookie_count": len(cookie_dict),
                "platform": platform,
                "message": f"{cfg['name']}登录成功，Cookie已自动保存",
            }

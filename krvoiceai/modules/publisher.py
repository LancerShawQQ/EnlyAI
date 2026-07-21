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

        # 确定目标平台：publish_platforms（多选） > platform（单选） > config enabled
        target_platforms = ctx.metadata.get("publish_platforms")
        if not target_platforms:
            # 向后兼容：单个 platform 字段
            single_platform = ctx.metadata.get("platform")
            if single_platform:
                target_platforms = [single_platform]
        if not target_platforms:
            target_platforms = [
                name for name, cfg in self.platforms_cfg.items()
                if cfg.get("enabled", False)
            ]
        if not target_platforms:
            target_platforms = ["bilibili"]  # 默认至少生成清单

        # auto_publish=True 时强制 auto 模式（实际发布，非仅生成清单）
        # 用户在向导中勾选"自动发布"意味着要真正发布到平台
        effective_mode = self.mode
        if ctx.metadata.get("auto_publish") and self.mode != "manual":
            effective_mode = "auto"

        self.logger.info(
            f"发布配置: mode={self.mode}→effective={effective_mode}, "
            f"platforms={target_platforms}, auto_publish={ctx.metadata.get('auto_publish')}, "
            f"video={ctx.final_video.name if ctx.final_video else 'None'}"
        )

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

        if effective_mode == "manual":
            return ModuleResult(
                success=True,
                data={
                    "mode": "manual",
                    "manifest": str(manifest_path),
                    "platforms": [t.platform for t in targets],
                    "message": "已生成发布清单，请手动发布",
                },
            )

        if effective_mode == "semi_auto":
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
            import tempfile
            from bilibili_api import video_uploader, Credential
            from bilibili_api.utils.picture import Picture

            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
            # 校验必要字段
            for k in ("SESSDATA", "bili_jct", "DedeUserID"):
                if not cookies.get(k):
                    raise ValueError(f"bilibili Cookie 缺少字段: {k}")

            # 1. 创建凭据（buvid3 可选但建议传）
            credential = Credential(
                sessdata=cookies["SESSDATA"],
                bili_jct=cookies["bili_jct"],
                dedeuserid=cookies["DedeUserID"],
                buvid3=cookies.get("buvid3", ""),
            )

            self.logger.info(f"B站发布开始: {target.title}")

            # 2. 创建上传分P
            page = video_uploader.VideoUploaderPage(
                path=str(target.video_path),
                title=target.title,
                description=target.description,
            )

            # 3. 准备封面（关键修复：cover="" 会导致 Picture().from_file("") 报错）
            # 策略：优先用 target.cover_path；无封面时用 ffmpeg 从视频提取一帧作为临时封面
            cover_picture: Picture = None  # type: ignore
            temp_cover_path = None
            if target.cover_path and Path(target.cover_path).exists():
                try:
                    cover_picture = Picture().from_file(str(target.cover_path))
                    self.logger.info(f"使用指定封面: {target.cover_path}")
                except Exception as e:
                    self.logger.warning(f"加载封面失败，将提取视频帧: {e}")
                    cover_picture = None

            if cover_picture is None:
                # 用 ffmpeg 从视频第 1 秒提取一帧作为封面
                # 关键：系统 PATH 中的 ffmpeg 可能是精简版（禁用了图片编码器），
                # 优先用 imageio-ffmpeg 自带的完整 ffmpeg
                import subprocess
                temp_cover_path = tempfile.mktemp(suffix=".jpg")
                ffmpeg_cmd = "ffmpeg"
                try:
                    import imageio_ffmpeg
                    ffmpeg_cmd = imageio_ffmpeg.get_ffmpeg_exe()
                    self.logger.debug(f"使用 imageio-ffmpeg: {ffmpeg_cmd}")
                except ImportError:
                    pass
                try:
                    subprocess.run(
                        [
                            ffmpeg_cmd, "-y", "-ss", "00:00:01", "-i", str(target.video_path),
                            "-vframes", "1", "-q:v", "2", temp_cover_path,
                        ],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                    cover_picture = Picture().from_file(temp_cover_path)
                    self.logger.info(f"已从视频提取封面帧: {temp_cover_path}")
                except Exception as e:
                    self.logger.warning(f"ffmpeg 提取封面失败: {e}")
                    # 兜底：用空 Picture 对象（B站 API 可能不接受，但避免初始化报错）
                    cover_picture = Picture()

            # 4. 视频元信息（用 VideoMeta 对象，避免 dict 格式的 cover 处理 bug）
            # tid 分区：122=野生技术协会（适合口播/知识）
            # tag: 列表格式，至少 1 个，最多 10 个
            tags = target.tags if target.tags else ["知识", "口播"]
            meta = video_uploader.VideoMeta(
                tid=122,
                title=target.title,
                desc=target.description or target.title,
                cover=cover_picture,
                tags=tags,
                original=True,  # 原创
            )

            # 5. 创建上传器
            uploader = video_uploader.VideoUploader(
                pages=[page],
                meta=meta,
                credential=credential,
            )

            # 6. 异步执行上传
            # 注意：在线程池中调用 asyncio.run() 是安全的（线程无事件循环）
            result = asyncio.run(uploader.start())

            # 清理临时封面
            if temp_cover_path:
                try:
                    Path(temp_cover_path).unlink(missing_ok=True)
                except Exception:
                    pass

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
        # 注意：选择器基于 2026-07-20 实际诊断抖音上传页 DOM 结构（test_douyin_publish_real.py 验证）
        # 关键发现（抖音上传页真实 DOM）：
        # 1. "高清发布"按钮初始就存在（class=douyin-creator-master-button-primary），不是上传完成的标志
        # 2. 真正的发布按钮是上传完成后新增的"发布"按钮（class=button-dhlUZE primary-cECiOJ）
        # 3. 标题输入框是 input[type=text][placeholder='填写作品标题，为作品获得更多流量']（不是 ql-editor）
        # 4. 上传完成标志：新增"发布"按钮 + "暂存离开"按钮 + 标题输入框出现
        # 5. "上传过程中请不要删除"文本在抖音页面根本不存在（旧逻辑误用此选择器导致 uploading_count 永远=0）
        # 6. 上传完成后的"检测中"进度条 class=progressing-QnBExK（内容审核进度，不是上传进度）
        platform_publish_cfg = {
            "douyin": {
                "publish_url": "https://creator.douyin.com/creator-micro/content/upload",
                "upload_input": "input[type=file]",
                # 标题输入框：抖音用 input[type=text]，placeholder 含"填写作品标题"
                "title_input": "input[placeholder*='填写作品标题'], input[placeholder*='标题']",
                # 描述输入框：抖音用 textarea，placeholder 含"描述"
                "desc_input": "textarea[placeholder*='描述'], .ql-editor[data-placeholder*='描述']",
                # 真正的发布按钮：上传完成后新增的"发布"按钮（class=button-dhlUZE primary-cECiOJ）
                # 注意：初始页面的"高清发布"按钮 class=douyin-creator-master-button-primary，不能匹配
                "publish_btn": "button.button-dhlUZE:has-text('发布'), button.primary-cECiOJ:has-text('发布')",
                # 上传完成标志：新增的"发布"按钮（最可靠）
                "upload_complete_btn_selector": "button.button-dhlUZE:has-text('发布'), button.primary-cECiOJ:has-text('发布')",
                # 上传完成辅助标志：标题输入框
                "upload_complete_title_selector": "input[placeholder*='填写作品标题']",
                # 内容审核进度条（"检测中2%"等，class=progressing-*）
                "upload_progress_selector": "[class*='progressing']",
                "cookie_domain": ".douyin.com",
                "name": "抖音",
            },
            "kuaishou": {
                # 基于 2026-07-20 dump_kuaishou_dom.py 诊断的真实 DOM 结构
                # 关键发现：
                # 1. 快手发布页**没有标题输入框**，只有"作品描述"（contenteditable 的 DIV）
                # 2. 描述输入框：<DIV id="work-description-edit" class="_description_17g9x_24" contenteditable="true">
                # 3. 发布按钮不是 <button>，是 <DIV>text='发布'，在 div[class*='edit-section-btns'] 容器中
                # 4. "立即发布"是单选选项（发布时间选择），不是发布按钮
                "publish_url": "https://cp.kuaishou.com/article/publish/video",
                "upload_input": "input[type=file]",
                # 快手无标题字段，title_input 设为空字符串，代码会跳过填写标题
                "title_input": "",
                # 描述输入框：contenteditable 的 DIV（不能用 fill()，需用 type()）
                "desc_input": "#work-description-edit, [contenteditable='true']",
                # 发布按钮：在 div[class*='edit-section-btns'] 容器中，点击只含"发布"文本的子 div
                "publish_btn": "div[class*='edit-section-btns'] div:has-text('发布'):not(:has-text('取消'))",
                # 上传完成判断：发布按钮容器出现 + 描述输入框出现
                "upload_complete_btn_selector": "div[class*='edit-section-btns']",
                "upload_complete_title_selector": "#work-description-edit, [contenteditable='true']",
                "upload_progress_selector": "[class*='progress'], [class*='Progress']",
                "cookie_domain": ".kuaishou.com",
                "name": "快手",
            },
            "wechat_video": {
                "publish_url": "https://channels.weixin.qq.com/platform/post/create",
                "upload_input": "input[type=file]",
                "title_input": "input[placeholder*='标题']",
                "desc_input": "textarea[placeholder*='描述']",
                "publish_btn": "button:has-text('发表')",
                # 视频号上传完成判断：标题输入框出现 + 发表按钮出现
                "upload_complete_btn_selector": "button:has-text('发表')",
                "upload_complete_title_selector": "input[placeholder*='标题']",
                "upload_progress_selector": "[class*='progress'], [class*='Progress']",
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
            # 关键：UA 必须完整，否则抖音会识别为非法客户端，拦截上传
            # viewport 要足够大（1440×900），否则部分元素可能不渲染
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            # 加载Cookie
            context.add_cookies(playwright_cookies)
            page = context.new_page()
            page.goto(cfg["publish_url"], wait_until="domcontentloaded")
            # SPA 需要充分渲染（3秒不够，改为 8 秒）
            time.sleep(8)
            # 如果跳到登录页说明Cookie失效
            if "login" in page.url.lower() or "passport" in page.url.lower():
                browser.close()
                target.status = "failed"
                target.error = f"{cfg['name']} Cookie已失效，请重新登录"
                return {"status": "failed", "error": target.error}

            try:
                # 1. 上传视频文件
                # 关键修复：等待上传 input 出现（最长 30 秒），而不是直接 set_input_files
                # 因为 SPA 可能需要更长时间渲染上传组件
                upload_input = page.locator(cfg["upload_input"]).first
                try:
                    upload_input.wait_for(state="attached", timeout=30000)
                except Exception:
                    # 如果等待 attached 失败，尝试点击"去上传"链接（快手特有）
                    try:
                        upload_link = page.locator("a.upload, a:has-text('去上传'), div.sketch.upload-video").first
                        if upload_link.count() > 0:
                            href = upload_link.get_attribute("href") or ""
                            if "passport" in href.lower() or "login" in href.lower():
                                browser.close()
                                target.status = "failed"
                                target.error = f"{cfg['name']} Cookie已失效（点击上传跳转到登录页），请重新登录"
                                return {"status": "failed", "error": target.error}
                            # href 不指向登录页，点击它
                            upload_link.click(timeout=5000)
                            time.sleep(3)
                            upload_input = page.locator(cfg["upload_input"]).first
                            upload_input.wait_for(state="attached", timeout=15000)
                    except Exception as e:
                        browser.close()
                        target.status = "failed"
                        target.error = f"{cfg['name']}未找到上传入口（input[type=file]），页面可能未渲染或Cookie失效: {e}"
                        return {"status": "failed", "error": target.error}

                upload_input.set_input_files(str(target.video_path))
                self.logger.info(f"已选择视频文件，等待上传...")
                # 等待上传完成（最长5分钟）
                # 关键改进：基于 2026-07-20 真实 DOM 诊断的正确判断逻辑
                # 抖音页面：
                #   - 初始状态："高清发布"按钮存在（class=douyin-creator-master-button-primary）
                #   - 上传完成后：新增"发布"按钮（class=button-dhlUZE primary-cECiOJ）+ "暂存离开"按钮 + 标题输入框
                #   - "上传过程中请不要删除"文本在抖音页面根本不存在（旧代码误用导致 uploading_count 永远=0）
                # 上传完成判断（任一条件满足即可）：
                #   1. 主要：上传完成后新增的"发布"按钮出现（最可靠）
                #   2. 辅助：标题输入框出现（上传完成后才渲染）
                upload_completed = False
                last_progress_log = 0
                # 记录初始"发布"按钮数量（初始状态为 0，上传完成后变 1）
                try:
                    initial_publish_btn_count = page.locator(cfg["upload_complete_btn_selector"]).count()
                except Exception:
                    initial_publish_btn_count = 0
                self.logger.info(f"初始'发布'按钮数量: {initial_publish_btn_count}（应为0，因为初始只有'高清发布'）")

                for i in range(150):  # 150 * 2 = 300 秒 = 5 分钟
                    time.sleep(2)
                    elapsed = (i + 1) * 2

                    # 主要标志：上传完成后新增的"发布"按钮出现
                    upload_complete_btn_sel = cfg.get("upload_complete_btn_selector")
                    publish_btn_count = 0
                    if upload_complete_btn_sel:
                        try:
                            publish_btn_count = page.locator(upload_complete_btn_sel).count()
                        except Exception:
                            publish_btn_count = 0

                    # 辅助标志：标题输入框出现
                    upload_complete_title_sel = cfg.get("upload_complete_title_selector")
                    title_count_for_complete = 0
                    if upload_complete_title_sel:
                        try:
                            title_count_for_complete = page.locator(upload_complete_title_sel).count()
                        except Exception:
                            title_count_for_complete = 0

                    # 上传完成的判断（兼容两种场景）：
                    # 场景 1（抖音）：初始无发布按钮，上传完成后新增 → publish_btn_count > initial
                    # 场景 2（快手草稿）：初始已有发布按钮（草稿），上传完成后仍为 1 → publish_btn_count > 0
                    # 共同条件：标题/描述输入框出现（title_count_for_complete > 0）
                    if title_count_for_complete > 0 and (
                        publish_btn_count > initial_publish_btn_count
                        or (publish_btn_count > 0 and initial_publish_btn_count > 0)
                    ):
                        upload_completed = True
                        self.logger.info(
                            f"上传完成（等待 {elapsed} 秒）：发布按钮={publish_btn_count}/{initial_publish_btn_count}, "
                            f"标题/描述框={title_count_for_complete}"
                        )
                        break

                    # 每30秒输出一次进度日志
                    if elapsed - last_progress_log >= 30:
                        # 尝试读取进度文本（如"检测中2%"）
                        progress_text = ""
                        progress_sel = cfg.get("upload_progress_selector")
                        if progress_sel:
                            try:
                                progress_el = page.locator(progress_sel).first
                                if progress_el.count() > 0:
                                    progress_text = progress_el.inner_text()[:80]
                            except Exception:
                                pass
                        self.logger.info(
                            f"上传中（{elapsed}秒）：发布按钮={publish_btn_count}/{initial_publish_btn_count}, "
                            f"标题框={title_count_for_complete}, 进度={progress_text!r}"
                        )
                        last_progress_log = elapsed

                if not upload_completed:
                    browser.close()
                    target.status = "failed"
                    target.error = f"{cfg['name']}视频上传超时（5分钟内未检测到上传完成标志：新增'发布'按钮 + 标题输入框）"
                    self.logger.error(target.error)
                    return {"status": "failed", "error": target.error}

                # 额外等待 3 秒让页面稳定
                time.sleep(3)

                # 关闭 react-joyride 引导遮罩（快手特有，会拦截点击事件）
                # 处理方式：直接用 JavaScript 删除 react-joyride-portal 元素
                # 注：Escape 键和点击 Skip 按钮都不可靠，直接删除 DOM 元素最稳定
                try:
                    removed = page.evaluate("""() => {
                        const portal = document.getElementById('react-joyride-portal');
                        if (portal) {
                            portal.remove();
                            return true;
                        }
                        return false;
                    }""")
                    if removed:
                        self.logger.info("已用 JS 删除 react-joyride 引导遮罩")
                    time.sleep(0.5)
                except Exception as e:
                    self.logger.debug(f"关闭 react-joyride 遮罩时异常（可忽略）: {e}")

                # 2. 填写标题
                # 快手无标题字段（title_input 为空字符串），跳过填写标题
                # 其他平台（抖音/视频号）正常填写
                if cfg.get("title_input"):
                    title_sel = page.locator(cfg["title_input"]).first
                    if title_sel.count() > 0:
                        try:
                            # 检测 contenteditable（富文本编辑器不能用 fill）
                            is_ce = title_sel.evaluate("el => el.getAttribute('contenteditable') === 'true'")
                            title_sel.click()
                            if is_ce:
                                title_sel.press("Control+a")
                                title_sel.press("Delete")
                                title_sel.type(target.title, delay=30)
                            else:
                                title_sel.fill(target.title)
                            self.logger.info(f"已填写标题: {target.title}")
                        except Exception as e:
                            self.logger.warning(f"填写标题失败: {e}")
                    else:
                        self.logger.warning(f"未找到标题输入框: {cfg['title_input']}")
                else:
                    self.logger.info(f"{cfg['name']}无标题字段，跳过填写标题")

                # 3. 填写描述
                if target.description:
                    desc_sel = page.locator(cfg["desc_input"]).first
                    if desc_sel.count() > 0:
                        try:
                            # 检测 contenteditable（富文本编辑器不能用 fill）
                            is_ce = desc_sel.evaluate("el => el.getAttribute('contenteditable') === 'true'")
                            desc_sel.click()
                            if is_ce:
                                desc_sel.press("Control+a")
                                desc_sel.press("Delete")
                                desc_sel.type(target.description, delay=30)
                            else:
                                desc_sel.fill(target.description)
                            self.logger.info(f"已填写描述")
                        except Exception as e:
                            self.logger.warning(f"填写描述失败: {e}")

                # 4. 等待用户确认（半自动模式：给用户3秒检查时间）
                time.sleep(3)

                # 5. 点击发布
                # 关键修复：点击上传完成后出现的"发布"按钮（不是初始的"高清发布"）
                # 关键修复 2：快手 react-joyride 遮罩会拦截点击，用 force=True 强制点击
                publish_btn = page.locator(cfg["publish_btn"]).first
                if publish_btn.count() > 0:
                    # 再次删除 react-joyride 遮罩（可能在填写过程中被重新创建）
                    try:
                        page.evaluate("""() => {
                            const portal = document.getElementById('react-joyride-portal');
                            if (portal) portal.remove();
                        }""")
                    except Exception:
                        pass
                    # force=True 绕过遮罩拦截，直接点击元素
                    # 注意：点击前获取 inner_text，因为点击后页面可能跳转导致元素失效
                    try:
                        btn_text = publish_btn.inner_text()
                    except Exception:
                        btn_text = "(无法获取文本)"
                    publish_btn.click(force=True)
                    self.logger.info(f"已点击发布按钮: {btn_text}")
                    # 等待发布完成（检测跳转或成功提示）
                    for _ in range(30):
                        time.sleep(2)
                        current_url = page.url
                        if "content/manage" in current_url or "success" in current_url.lower():
                            self.logger.info(f"检测到发布成功跳转: {current_url}")
                            break
                        try:
                            if page.locator("text='发布成功'").count() > 0:
                                self.logger.info(f"检测到发布成功提示")
                                break
                        except Exception:
                            pass
                    time.sleep(5)
                else:
                    # 发布按钮找不到时标记为 failed
                    browser.close()
                    target.status = "failed"
                    target.error = f"{cfg['name']}未找到发布按钮（选择器: {cfg['publish_btn']}），视频已上传但未发布"
                    self.logger.error(target.error)
                    return {"status": "failed", "error": target.error}

                # 提取发布后的视频URL
                final_url = page.url
                browser.close()

                target.status = "success"
                target.url = final_url
                self.logger.info(f"{cfg['name']}发布完成，跳转URL: {final_url}")
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
        # 关键改进：登录成功判断改为"反向判断"——检查登录表单是否消失
        # 而不是检查特定 success_elements 是否出现（不同平台 SPA 渲染差异大）
        platform_cfg = {
            "douyin": {
                "login_url": "https://creator.douyin.com/creator-micro/home",
                "success_url_contains": "creator.douyin.com",
                # 登录表单元素（登录成功后会消失）
                "login_form_selectors": [
                    "input[type='tel']",                # 手机号输入框
                    "input[type='password']",           # 密码输入框
                    "input[name*='phone']",
                    "input[name*='login']",
                    "input[placeholder*='手机']",
                    "input[placeholder*='密码']",
                    "[class*='qrcode-login']",
                    "[class*='login-form']",
                    "[class*='login_comp']",
                ],
                # 额外确认元素（登录成功后才有的，用于二次确认）
                "success_confirm_selectors": [
                    "[class*='avatar']",
                    "[class*='userInfo']",
                    "[class*='user-info']",
                    "[class*='sidebar']",
                    "[class*='menu-item']",
                    ".ant-avatar",
                    ".ant-layout-sider",
                    "input[type=file]",
                    "[class*='upload']",
                ],
                "cookie_domains": [".douyin.com", ".iesdouyin.com", ".amemv.com"],
                "name": "抖音创作者",
            },
            "kuaishou": {
                "login_url": "https://cp.kuaishou.com/article/publish/video",
                "success_url_contains": "cp.kuaishou.com",
                "login_form_selectors": [
                    "input[type='tel']",
                    "input[type='password']",
                    "input[name*='phone']",
                    "input[placeholder*='手机']",
                    "input[placeholder*='密码']",
                    "[class*='login-form']",
                    "[class*='qrcode']",
                    # 快手未登录介绍页的"立即登录"按钮
                    "button:has-text('立即登录')",
                    "a:has-text('立即登录')",
                ],
                "success_confirm_selectors": [
                    "input[type=file]",
                    "textarea[placeholder*='描述']",
                    "[class*='upload']:not([class*='uploaded'])",
                ],
                # 关键修复：快手必须检测到 input[type=file] 才认为登录成功
                # 原因：快手未登录介绍页没有 input[type=tel] 等表单元素（用二维码登录），
                # 但有 [class*='upload']（"去上传"链接），导致旧逻辑误判为已登录
                # 要求 input[type=file] 出现才能真正确认登录成功
                "required_confirm_selectors": ["input[type=file]"],
                # 快手特殊：需要检查"去上传"链接是否指向 passport
                "check_upload_link": True,
                "cookie_domains": [".kuaishou.com", ".yximgs.com"],
                "name": "快手创作者",
            },
            "wechat_video": {
                "login_url": "https://channels.weixin.qq.com/platform/post/create",
                "success_url_contains": "channels.weixin.qq.com",
                "login_form_selectors": [
                    "input[type='tel']",
                    "input[type='password']",
                    "[class*='qrcode']",
                    "[class*='login']",
                    # 微信扫码登录特有的元素
                    "[class*='qr']",
                    "[class*='scan']",
                    "img[src*='qrcode']",
                    "div[class*='login-container']",
                    "div[class*='login-content']",
                ],
                "success_confirm_selectors": [
                    "input[type=file]",
                    "[class*='upload']",
                    "textarea[placeholder*='描述']",
                    "[class*='avatar']",
                    "[class*='sidebar']",
                    ".ant-layout-sider",
                ],
                # 关键修复：视频号必须检测到 input[type=file] 才认为登录成功
                # 避免登录页的 [class*='login'] 元素消失但实际未登录的场景误判
                "required_confirm_selectors": ["input[type=file]"],
                "cookie_domains": [".qq.com"],
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
            # 判断逻辑（反向判断）：
            # 1. URL 在创作者后台 且 不在 login/passport 页
            # 2. 页面没有登录表单元素（input[type='tel'] 等）
            # 3. （可选）有登录成功后才有的元素（用于二次确认）
            import time
            max_wait = 300  # 5分钟
            start = time.time()
            logged_in = False
            last_log_time = start
            log_interval = 15  # 每15秒输出一次状态日志

            self.logger.info(f"请在弹出的浏览器中登录{cfg['name']}账号...")
            self.logger.info(f"判断逻辑：URL在创作者后台 + 无登录表单元素 + 有登录后才有的元素")

            while time.time() - start < max_wait:
                try:
                    current_url = page.url
                    url_lower = current_url.lower()

                    # 第1层判断：URL 不在登录页
                    url_ok = (
                        cfg["success_url_contains"] in current_url
                        and "login" not in url_lower
                        and "passport" not in url_lower
                    )

                    # 关键修复：即使 URL 仍在 passport，也检测 input[type=file] 是否出现
                    # 原因：快手登录成功后，URL 可能短暂停留在 passport，但页面已经跳转
                    # 或者：用户扫码后页面跳转到了创作者后台，但 page.url 更新有延迟
                    # 如果检测到 input[type=file]，强制认为已登录成功
                    if not url_ok:
                        try:
                            if page.locator("input[type=file]").count() > 0:
                                self.logger.info(f"URL 仍在 {current_url[:60]}，但检测到 input[type=file]，强制认为已登录")
                                url_ok = True
                        except Exception:
                            pass

                    if url_ok:
                        # 等待 SPA 渲染
                        time.sleep(3)

                        # 第2层判断：检查登录表单元素是否消失（反向判断）
                        login_form_count = 0
                        for sel in cfg["login_form_selectors"]:
                            try:
                                count = page.locator(sel).count()
                                if count > 0:
                                    login_form_count += count
                            except Exception:
                                pass

                        if login_form_count == 0:
                            # 第3层判断：检查是否有登录成功后才有的元素（二次确认）
                            # 注意：确认元素是辅助判断，不是必要条件
                            # 只要 URL 在创作者后台 + 无登录表单，就认为登录成功
                            has_confirm = False
                            confirm_selector_found = ""
                            for sel in cfg["success_confirm_selectors"]:
                                try:
                                    if page.locator(sel).count() > 0:
                                        has_confirm = True
                                        confirm_selector_found = sel
                                        break
                                except Exception:
                                    pass

                            if has_confirm:
                                self.logger.info(f"检测到登录成功确认元素: {confirm_selector_found}")
                            else:
                                self.logger.info(f"未检测到确认元素，但URL和表单判断已通过")

                            # 关键修复：检查必要确认元素（required_confirm_selectors）
                            # 对于快手等平台，必须检测到 input[type=file] 才认为真正登录成功
                            # 避免未登录介绍页（无登录表单但有"去上传"链接）被误判
                            required_selectors = cfg.get("required_confirm_selectors", [])
                            if required_selectors:
                                all_required_found = True
                                missing_required = []
                                for sel in required_selectors:
                                    try:
                                        if page.locator(sel).count() == 0:
                                            all_required_found = False
                                            missing_required.append(sel)
                                    except Exception:
                                        all_required_found = False
                                        missing_required.append(sel)

                                if not all_required_found:
                                    if time.time() - last_log_time > log_interval:
                                        self.logger.info(f"必要确认元素未出现: {missing_required}，继续等待用户完成登录...")
                                        last_log_time = time.time()
                                    continue  # 必要元素未出现，继续等待

                            # 快手特殊检查：确认"去上传"链接不指向 passport
                            # 注意：此检查可能因页面 DOM 缓存导致误判，改为 warning 而非 continue
                            # 只要 URL 在创作者后台 + 无登录表单 + 有确认元素，就认为登录成功
                            # Cookie 是否真正有效，由后续 login_check / test_video_upload 验证
                            if cfg.get("check_upload_link"):
                                try:
                                    upload_link = page.locator("a.upload, a:has-text('去上传')").first
                                    if upload_link.count() > 0:
                                        href = upload_link.get_attribute("href") or ""
                                        if "passport" in href.lower() or "login" in href.lower():
                                            # "去上传"指向登录页，可能是页面 DOM 缓存，记录 warning 但不阻塞
                                            if time.time() - last_log_time > log_interval:
                                                self.logger.warning(f"URL和表单判断通过，但'去上传'链接指向 passport（可能是DOM缓存），仍尝试保存Cookie...")
                                                last_log_time = time.time()
                                            # 不再 continue，继续走登录成功流程
                                        else:
                                            self.logger.info(f"快手'去上传'链接正常: {href}")
                                except Exception:
                                    pass

                            # 所有判断通过，登录成功
                            # 关键改进：只要 URL 在创作者后台 + 无登录表单 + （快手特有）去上传链接正常
                            # 就认为登录成功，不强制要求有确认元素
                            time.sleep(2)  # 再等2秒确认稳定
                            logged_in = True
                            self.logger.info(f"登录成功判断通过：URL={url_ok}, 无登录表单({login_form_count}), 有确认元素={has_confirm}")
                            break
                        else:
                            # 有登录表单，说明还在登录页
                            if time.time() - last_log_time > log_interval:
                                self.logger.info(f"检测到登录表单元素({login_form_count}个)，等待用户完成登录...")
                                last_log_time = time.time()
                    else:
                        # URL 还在登录页
                        if time.time() - last_log_time > log_interval:
                            self.logger.info(f"URL 仍在登录页({current_url})，等待用户登录...")
                            last_log_time = time.time()
                except Exception as e:
                    if time.time() - last_log_time > log_interval:
                        self.logger.warning(f"登录检测异常: {e}")
                        last_log_time = time.time()
                time.sleep(2)

            if not logged_in:
                browser.close()
                return {"success": False, "error": f"登录超时（5分钟未检测到{cfg['name']}登录成功，请确保登录后页面显示创作者后台而非登录表单）"}

            # 登录成功，提取所有 Cookie
            # 关键修复：保存所有相关域的 Cookie，不仅限于主域
            cookies = context.cookies()
            browser.close()

            # 转为 {name: value} 字典保存（匹配任一相关域名）
            cookie_domains = cfg["cookie_domains"]
            cookie_dict = {}
            for c in cookies:
                domain = c.get("domain", "")
                # 匹配域名：domain 可能是 .douyin.com 或 douyin.com
                if any(domain == d or domain.endswith(d) or domain == d.lstrip(".")
                       for d in cookie_domains):
                    cookie_dict[c["name"]] = c["value"]

            if not cookie_dict:
                return {"success": False, "error": "登录成功但未提取到Cookie（请重试）"}

            # 保存
            self.save_cookie(platform, cookie_dict)
            self.logger.info(f"{cfg['name']}登录成功，已保存 {len(cookie_dict)} 个Cookie（域名: {cookie_domains}）")
            return {
                "success": True,
                "cookie_count": len(cookie_dict),
                "platform": platform,
                "message": f"{cfg['name']}登录成功，Cookie已自动保存",
            }

    # ============ 发布测试台（4 阶段测试链路） ============

    # 平台发布页配置（与 _publish_playwright 保持一致，供测试方法复用）
    _TEST_PLATFORM_CFG = {
        "bilibili": {
            "check_url": "https://api.bilibili.com/x/web-interface/nav",
            "cookie_domain": ".bilibili.com",
            "name": "B站",
            "method": "api",
        },
        "douyin": {
            # 与 _publish_playwright 的 platform_publish_cfg 保持一致
            # 基于 2026-07-20 实际 DOM 诊断（test_douyin_publish_real.py 验证）
            "publish_url": "https://creator.douyin.com/creator-micro/content/upload",
            "check_url": "https://creator.douyin.com/creator-micro/home",
            "upload_input": "input[type=file]",
            # 标题输入框：抖音用 input[type=text]，placeholder 含"填写作品标题"
            "title_input": "input[placeholder*='填写作品标题'], input[placeholder*='标题']",
            # 描述输入框：抖音用 textarea，placeholder 含"描述"
            "desc_input": "textarea[placeholder*='描述'], .ql-editor[data-placeholder*='描述']",
            # 真正的发布按钮：上传完成后新增的"发布"按钮（class=button-dhlUZE primary-cECiOJ）
            "publish_btn": "button.button-dhlUZE:has-text('发布'), button.primary-cECiOJ:has-text('发布')",
            # 上传完成标志：新增的"发布"按钮（最可靠）
            "upload_complete_btn_selector": "button.button-dhlUZE:has-text('发布'), button.primary-cECiOJ:has-text('发布')",
            # 上传完成辅助标志：标题输入框
            "upload_complete_title_selector": "input[placeholder*='填写作品标题']",
            # 内容审核进度条（"检测中2%"等，class=progressing-*）
            "upload_progress_selector": "[class*='progressing']",
            "cookie_domain": ".douyin.com",
            "name": "抖音",
            "method": "playwright",
        },
        "kuaishou": {
            # 与 platform_publish_cfg 的快手配置保持一致
            # 基于 2026-07-20 dump_kuaishou_dom.py 诊断的真实 DOM 结构
            "publish_url": "https://cp.kuaishou.com/article/publish/video",
            "check_url": "https://cp.kuaishou.com/article/publish/video",
            "upload_input": "input[type=file]",
            "title_input": "",
            "desc_input": "#work-description-edit, [contenteditable='true']",
            "publish_btn": "div[class*='edit-section-btns'] div:has-text('发布'):not(:has-text('取消'))",
            "upload_complete_btn_selector": "div[class*='edit-section-btns']",
            "upload_complete_title_selector": "#work-description-edit, [contenteditable='true']",
            "upload_progress_selector": "[class*='progress'], [class*='Progress']",
            "cookie_domain": ".kuaishou.com",
            "name": "快手",
            "method": "playwright",
        },
        "wechat_video": {
            "publish_url": "https://channels.weixin.qq.com/platform/post/create",
            "check_url": "https://channels.weixin.qq.com/platform/post/create",
            "upload_input": "input[type=file]",
            "title_input": "input[placeholder*='标题']",
            "desc_input": "textarea[placeholder*='描述']",
            "publish_btn": "button:has-text('发表')",
            "upload_complete_btn_selector": "button:has-text('发表')",
            "upload_complete_title_selector": "input[placeholder*='标题']",
            "upload_progress_selector": "[class*='progress'], [class*='Progress']",
            "cookie_domain": ".qq.com",
            "name": "视频号",
            "method": "playwright",
        },
    }

    def test_cookie_files(self) -> dict:
        """测试 1：Cookie 文件检查
        检查各平台 Cookie 文件是否存在、字段是否完整
        """
        result = {}
        bilibili_required = ["SESSDATA", "bili_jct", "DedeUserID"]

        for platform in ("bilibili", "douyin", "kuaishou", "wechat_video"):
            cookie_file = self.cookies_dir / f"{platform}.json"
            info = {
                "platform": platform,
                "file_exists": cookie_file.exists(),
                "file_path": str(cookie_file),
            }

            if cookie_file.exists():
                try:
                    cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
                    info["cookie_count"] = len(cookies)
                    info["cookie_keys"] = list(cookies.keys())[:10]

                    if platform == "bilibili":
                        missing = [k for k in bilibili_required if k not in cookies]
                        info["required_fields"] = bilibili_required
                        info["missing_fields"] = missing
                        info["valid"] = len(missing) == 0
                    else:
                        info["valid"] = len(cookies) >= 5
                        info["min_required_count"] = 5
                except Exception as e:
                    info["valid"] = False
                    info["error"] = f"Cookie 文件解析失败: {e}"
            else:
                info["valid"] = False
                info["error"] = "Cookie 文件不存在"

            result[platform] = info

        return {"success": True, "platforms": result}

    def test_login_status(self, platform: str) -> dict:
        """测试 2：登录态真实性校验
        实际加载 Cookie 访问平台，检测是否被重定向到登录页
        """
        cfg = self._TEST_PLATFORM_CFG.get(platform)
        if not cfg:
            return {"success": False, "error": f"不支持的平台: {platform}"}

        cookie_file = self.cookies_dir / f"{platform}.json"
        if not cookie_file.exists():
            return {
                "success": False,
                "error": f"{platform} Cookie 文件不存在",
                "file_path": str(cookie_file),
            }

        try:
            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
        except Exception as e:
            return {"success": False, "error": f"Cookie 文件解析失败: {e}"}

        # B 站用 API 校验
        if platform == "bilibili":
            try:
                import requests
                sessdata = cookies.get("SESSDATA", "")
                bili_jct = cookies.get("bili_jct", "")
                dedeuserid = cookies.get("DedeUserID", "")
                resp = requests.get(
                    "https://api.bilibili.com/x/web-interface/nav",
                    cookies={"SESSDATA": sessdata, "bili_jct": bili_jct, "DedeUserID": dedeuserid},
                    timeout=10,
                )
                data = resp.json()
                if data.get("code") == 0:
                    user_info = data.get("data", {})
                    return {
                        "success": True,
                        "platform": platform,
                        "logged_in": True,
                        "username": user_info.get("uname", ""),
                        "uid": user_info.get("mid", ""),
                        "is_login": user_info.get("isLogin", False),
                        "check_method": "api",
                        "message": f"{cfg['name']}登录态有效",
                    }
                else:
                    return {
                        "success": True,
                        "platform": platform,
                        "logged_in": False,
                        "code": data.get("code"),
                        "message": data.get("message", "登录态失效"),
                        "check_method": "api",
                    }
            except Exception as e:
                return {"success": False, "error": f"B站 API 校验失败: {e}"}

        # 其他平台用 Playwright 校验（headless）
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "error": "playwright 未安装"}

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
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            context.add_cookies(playwright_cookies)
            page = context.new_page()

            try:
                page.goto(cfg["check_url"], wait_until="domcontentloaded", timeout=30000)
                # 快手等 SPA 需要更长时间渲染上传表单
                time.sleep(8)
                current_url = page.url
                is_login_redirect = (
                    "login" in current_url.lower()
                    or "passport" in current_url.lower()
                    or "login_page" in current_url.lower()
                )

                has_login_form = False
                try:
                    login_elements = page.locator(
                        "input[type='tel'], input[type='password'], .login-form, .qrcode-login"
                    ).count()
                    has_login_form = login_elements > 0
                except Exception:
                    pass

                # 深度登录态校验：检查"去上传"链接的 href 是否指向登录页
                # 某些平台（如快手）URL 不跳转，但页面上"去上传"链接指向 passport 登录页
                upload_link_to_login = False
                upload_link_href = ""
                try:
                    # 查找所有可能的"去上传"链接
                    upload_links = page.locator("a.upload, a:has-text('去上传'), a:has-text('上传')").all()
                    for link in upload_links[:3]:
                        href = link.get_attribute("href") or ""
                        if href and ("login" in href.lower() or "passport" in href.lower()):
                            upload_link_to_login = True
                            upload_link_href = href
                            break
                except Exception:
                    pass

                # 检查是否有真正的上传 input（登录态有效时才会渲染）
                has_real_upload_input = False
                try:
                    has_real_upload_input = page.locator("input[type='file']").count() > 0
                except Exception:
                    pass

                # 深度登录态判断：任一异常信号即视为未登录
                # 1. URL 被重定向到登录页
                # 2. 页面出现登录表单元素
                # 3. "去上传"链接指向 passport 登录页（快手特有：URL 不跳转但实际未登录）
                not_logged_in_signals = is_login_redirect or has_login_form or upload_link_to_login
                logged_in = not not_logged_in_signals

                result = {
                    "success": True,
                    "platform": platform,
                    "logged_in": logged_in,
                    "final_url": current_url,
                    "is_login_redirect": is_login_redirect,
                    "has_login_form": has_login_form,
                    "upload_link_to_login": upload_link_to_login,
                    "upload_link_href": upload_link_href,
                    "has_real_upload_input": has_real_upload_input,
                    "check_method": "playwright",
                    "message": f"{cfg['name']}登录态{'有效' if logged_in else '失效（' + ('被重定向到登录页' if is_login_redirect else ('上传链接指向登录页' if upload_link_to_login else ('页面有登录表单' if has_login_form else '未渲染上传表单'))) + '）'}",
                }
                browser.close()
                return result

            except Exception as e:
                browser.close()
                return {
                    "success": False,
                    "platform": platform,
                    "error": f"页面访问失败: {e}",
                    "check_method": "playwright",
                }

    def test_page_selectors(self, platform: str) -> dict:
        """测试 3：页面选择器探测
        验证各平台发布页的 upload_input/title_input/publish_btn 选择器是否能定位到
        """
        cfg = self._TEST_PLATFORM_CFG.get(platform)
        if not cfg or platform == "bilibili":
            return {
                "success": False,
                "error": f"不支持的平台: {platform}（B站走 API 无需选择器，其他仅支持 douyin/kuaishou/wechat_video）",
            }

        cookie_file = self.cookies_dir / f"{platform}.json"
        if not cookie_file.exists():
            return {"success": False, "error": f"{platform} Cookie 文件不存在"}

        try:
            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
        except Exception as e:
            return {"success": False, "error": f"Cookie 文件解析失败: {e}"}

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "error": "playwright 未安装"}

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
            browser = p.chromium.launch(headless=False)  # 选择器探测用非无头，方便观察
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            context.add_cookies(playwright_cookies)
            page = context.new_page()

            try:
                page.goto(cfg["publish_url"], wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)

                current_url = page.url
                if "login" in current_url.lower() or "passport" in current_url.lower():
                    browser.close()
                    return {
                        "success": False,
                        "platform": platform,
                        "error": f"{cfg['name']} Cookie已失效，请重新登录",
                        "final_url": current_url,
                    }

                selectors_to_test = {
                    "upload_input": cfg["upload_input"],
                    "title_input": cfg.get("title_input", ""),
                    "desc_input": cfg["desc_input"],
                    "publish_btn": cfg["publish_btn"],
                }

                selector_results = {}
                for name, selector in selectors_to_test.items():
                    # 快手 title_input 为空字符串（无标题字段），直接标记为 skipped
                    if not selector:
                        selector_results[name] = {
                            "selector": "",
                            "found": True,
                            "count": 0,
                            "note": "该平台无此字段（如快手无标题）",
                        }
                        continue
                    try:
                        count = page.locator(selector).count()
                        selector_results[name] = {
                            "selector": selector,
                            "found": count > 0,
                            "count": count,
                        }
                    except Exception as e:
                        selector_results[name] = {
                            "selector": selector,
                            "found": False,
                            "error": str(e),
                        }

                all_found = all(s["found"] for s in selector_results.values())

                result = {
                    "success": True,
                    "platform": platform,
                    "final_url": current_url,
                    "selectors": selector_results,
                    "all_found": all_found,
                    "message": f"{cfg['name']} 选择器探测{'全部找到' if all_found else '部分缺失，可能页面结构已变化'}",
                }

                time.sleep(3)  # 等待用户观察
                browser.close()
                return result

            except Exception as e:
                browser.close()
                return {
                    "success": False,
                    "platform": platform,
                    "error": f"页面访问失败: {e}",
                }

    def test_video_upload(
        self,
        platform: str,
        video_path: str,
        dry_run: bool = True,
        title: str = "",
        description: str = "",
    ) -> dict:
        """测试 4：实际上传测试
        上传视频文件到平台发布页，验证上传流程是否正常

        Args:
            platform: 平台名（bilibili/douyin/kuaishou/wechat_video）
            video_path: 测试视频路径
            dry_run: True=仅上传不点发布按钮；False=点击发布按钮（真实发布）
            title: 视频标题
            description: 视频描述
        """
        # B 站走 API
        if platform == "bilibili":
            return self._test_bilibili_upload(video_path, dry_run, title, description)

        cfg = self._TEST_PLATFORM_CFG.get(platform)
        if not cfg:
            return {"success": False, "error": f"不支持的平台: {platform}"}

        video_p = Path(video_path)
        if not video_p.exists():
            return {"success": False, "error": f"视频文件不存在: {video_path}"}

        cookie_file = self.cookies_dir / f"{platform}.json"
        if not cookie_file.exists():
            return {"success": False, "error": f"{platform} Cookie 文件不存在"}

        try:
            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
        except Exception as e:
            return {"success": False, "error": f"Cookie 文件解析失败: {e}"}

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "error": "playwright 未安装"}

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
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            context.add_cookies(playwright_cookies)
            page = context.new_page()

            try:
                page.goto(cfg["publish_url"], wait_until="domcontentloaded", timeout=30000)
                # SPA 需要充分渲染（3秒不够，改为 8 秒，与诊断脚本一致）
                time.sleep(8)

                current_url = page.url
                if "login" in current_url.lower() or "passport" in current_url.lower():
                    browser.close()
                    return {
                        "success": False,
                        "platform": platform,
                        "error": f"{cfg['name']} Cookie已失效，请重新登录",
                        "final_url": current_url,
                    }

                # 上传视频文件
                # 关键：等待 input[type=file] 真正可交互（attached 状态），否则 set_input_files 可能无效
                upload_input = page.locator(cfg["upload_input"]).first
                try:
                    upload_input.wait_for(state="attached", timeout=10000)
                except Exception as e:
                    browser.close()
                    return {
                        "success": False,
                        "platform": platform,
                        "error": f"未找到上传入口（{cfg['upload_input']}），页面可能未渲染: {e}",
                    }
                upload_input.set_input_files(str(video_p))
                self.logger.info(f"[测试] 已选择视频文件: {video_p.name}")

                # 等待上传完成（最长 5 分钟）
                # 关键改进：基于 2026-07-20 真实 DOM 诊断的正确判断逻辑
                # 抖音页面：
                #   - 初始状态："高清发布"按钮存在（class=douyin-creator-master-button-primary）
                #   - 上传完成后：新增"发布"按钮（class=button-dhlUZE primary-cECiOJ）+ 标题输入框
                #   - "上传过程中请不要删除"文本在抖音页面根本不存在（旧逻辑误用导致 uploading_count 永远=0）
                # 上传完成判断：新增"发布"按钮出现 + 标题输入框出现
                upload_complete = False
                last_progress_log = 0
                # 记录初始"发布"按钮数量
                upload_complete_btn_sel = cfg.get("upload_complete_btn_selector")
                upload_complete_title_sel = cfg.get("upload_complete_title_selector")
                progress_sel = cfg.get("upload_progress_selector")
                try:
                    initial_publish_btn_count = page.locator(upload_complete_btn_sel).count() if upload_complete_btn_sel else 0
                except Exception:
                    initial_publish_btn_count = 0
                self.logger.info(f"[测试] 初始'发布'按钮数量: {initial_publish_btn_count}")

                for i in range(150):  # 150 * 2 = 300 秒 = 5 分钟
                    time.sleep(2)
                    elapsed = (i + 1) * 2

                    # 主要标志：上传完成后新增的"发布"按钮出现
                    publish_btn_count = 0
                    if upload_complete_btn_sel:
                        try:
                            publish_btn_count = page.locator(upload_complete_btn_sel).count()
                        except Exception:
                            publish_btn_count = 0

                    # 辅助标志：标题输入框出现
                    title_count_for_complete = 0
                    if upload_complete_title_sel:
                        try:
                            title_count_for_complete = page.locator(upload_complete_title_sel).count()
                        except Exception:
                            title_count_for_complete = 0

                    # 上传完成的判断（兼容两种场景）：
                    # 场景 1（抖音）：初始无发布按钮，上传完成后新增 → publish_btn_count > initial
                    # 场景 2（快手草稿）：初始已有发布按钮（草稿），上传完成后仍为 1 → publish_btn_count > 0
                    # 共同条件：标题/描述输入框出现（title_count_for_complete > 0）
                    if title_count_for_complete > 0 and (
                        publish_btn_count > initial_publish_btn_count
                        or (publish_btn_count > 0 and initial_publish_btn_count > 0)
                    ):
                        upload_complete = True
                        self.logger.info(
                            f"[测试] 上传完成（等待 {elapsed} 秒）：发布按钮={publish_btn_count}/{initial_publish_btn_count}, "
                            f"标题/描述框={title_count_for_complete}"
                        )
                        break

                    # 每30秒输出一次进度日志
                    if elapsed - last_progress_log >= 30:
                        progress_text = ""
                        if progress_sel:
                            try:
                                progress_el = page.locator(progress_sel).first
                                if progress_el.count() > 0:
                                    progress_text = progress_el.inner_text()[:80]
                            except Exception:
                                pass
                        # 关键诊断：打印页面 URL 和前 3 行文本，找出页面卡在哪里
                        try:
                            diag_url = page.url
                            diag_text = page.locator("body").inner_text()[:120].replace("\n", " | ")
                        except Exception as e:
                            diag_url = f"ERR: {e}"
                            diag_text = ""
                        # 关键诊断：列出所有标签页
                        try:
                            pages = page.context.pages
                            pages_info = " | ".join([f"#{i}: {p.url[:60]}" for i, p in enumerate(pages)])
                        except Exception:
                            pages_info = ""
                        self.logger.info(
                            f"[测试] 上传中（{elapsed}秒）：发布按钮={publish_btn_count}/{initial_publish_btn_count}, "
                            f"标题框={title_count_for_complete}, 进度={progress_text!r}, "
                            f"URL={diag_url[:80]}, 文本={diag_text[:80]}, 标签页=[{pages_info}]"
                        )
                        last_progress_log = elapsed

                if not upload_complete:
                    browser.close()
                    return {
                        "success": False,
                        "platform": platform,
                        "error": "上传超时（5分钟内未检测到上传完成标志：新增'发布'按钮 + 标题输入框）",
                    }

                # 额外等待 3 秒让页面稳定
                time.sleep(3)

                # 关闭 react-joyride 引导遮罩（快手特有，会拦截点击事件）
                # 直接用 JavaScript 删除 react-joyride-portal 元素
                try:
                    removed = page.evaluate("""() => {
                        const portal = document.getElementById('react-joyride-portal');
                        if (portal) {
                            portal.remove();
                            return true;
                        }
                        return false;
                    }""")
                    if removed:
                        self.logger.info("[测试] 已用 JS 删除 react-joyride 引导遮罩")
                    time.sleep(0.5)
                except Exception as e:
                    self.logger.debug(f"[测试] 关闭 react-joyride 遮罩时异常（可忽略）: {e}")

                # 填写标题
                # 快手无标题字段（title_input 为空字符串），跳过填写标题
                if title and cfg.get("title_input"):
                    title_sel = page.locator(cfg["title_input"]).first
                    if title_sel.count() > 0:
                        try:
                            is_ce = title_sel.evaluate("el => el.getAttribute('contenteditable') === 'true'")
                            title_sel.click()
                            if is_ce:
                                title_sel.press("Control+a")
                                title_sel.press("Delete")
                                title_sel.type(title, delay=30)
                            else:
                                title_sel.fill(title)
                            self.logger.info(f"[测试] 已填写标题: {title}")
                        except Exception as e:
                            self.logger.warning(f"[测试] 填写标题失败: {e}")

                # 填写描述
                if description:
                    desc_sel = page.locator(cfg["desc_input"]).first
                    if desc_sel.count() > 0:
                        try:
                            is_ce = desc_sel.evaluate("el => el.getAttribute('contenteditable') === 'true'")
                            desc_sel.click()
                            if is_ce:
                                desc_sel.press("Control+a")
                                desc_sel.press("Delete")
                                desc_sel.type(description, delay=30)
                            else:
                                desc_sel.fill(description)
                            self.logger.info(f"[测试] 已填写描述")
                        except Exception as e:
                            self.logger.warning(f"[测试] 填写描述失败: {e}")

                if dry_run:
                    time.sleep(5)  # 等待用户观察
                    browser.close()
                    return {
                        "success": True,
                        "platform": platform,
                        "uploaded": True,
                        "dry_run": True,
                        "title_filled": bool(title),
                        "description_filled": bool(description),
                        "message": f"{cfg['name']} 视频已上传成功（dry-run 模式，未点击发布按钮）",
                    }
                else:
                    # 关键修复：点击上传完成后出现的"发布"按钮（不是初始的"高清发布"）
                    # 关键修复 2：快手 react-joyride 遮罩会拦截点击，用 force=True 强制点击
                    publish_btn = page.locator(cfg["publish_btn"]).first
                    if publish_btn.count() == 0:
                        browser.close()
                        return {
                            "success": False,
                            "platform": platform,
                            "error": f"未找到发布按钮（选择器: {cfg['publish_btn']}），视频已上传但未发布",
                        }
                    # 再次删除 react-joyride 遮罩（可能在填写过程中被重新创建）
                    try:
                        page.evaluate("""() => {
                            const portal = document.getElementById('react-joyride-portal');
                            if (portal) portal.remove();
                        }""")
                    except Exception:
                        pass
                    # force=True 绕过遮罩拦截，直接点击元素
                    # 注意：点击前获取 inner_text，因为点击后页面可能跳转导致元素失效
                    try:
                        btn_text = publish_btn.inner_text()
                    except Exception:
                        btn_text = "(无法获取文本)"
                    publish_btn.click(force=True)
                    self.logger.info(f"[测试] 已点击发布按钮: {btn_text}")
                    # 等待发布完成（检测跳转或成功提示）
                    for _ in range(30):
                        time.sleep(2)
                        current_url = page.url
                        if "content/manage" in current_url or "success" in current_url.lower():
                            self.logger.info(f"[测试] 检测到发布成功跳转: {current_url}")
                            break
                        try:
                            if page.locator("text='发布成功'").count() > 0:
                                self.logger.info(f"[测试] 检测到发布成功提示")
                                break
                        except Exception:
                            pass
                    time.sleep(5)
                    final_url = page.url
                    browser.close()
                    return {
                        "success": True,
                        "platform": platform,
                        "uploaded": True,
                        "published": True,
                        "dry_run": False,
                        "final_url": final_url,
                        "message": f"{cfg['name']} 视频已发布成功",
                    }

            except Exception as e:
                browser.close()
                return {
                    "success": False,
                    "platform": platform,
                    "error": f"上传过程出错: {e}",
                }

    def _test_bilibili_upload(
        self,
        video_path: str,
        dry_run: bool = True,
        title: str = "",
        description: str = "",
    ) -> dict:
        """B站上传测试（走 API）"""
        video_p = Path(video_path)
        if not video_p.exists():
            return {"success": False, "error": f"视频文件不存在: {video_path}"}

        cookie_file = self.cookies_dir / "bilibili.json"
        if not cookie_file.exists():
            return {"success": False, "error": "B站 Cookie 文件不存在"}

        try:
            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
        except Exception as e:
            return {"success": False, "error": f"Cookie 文件解析失败: {e}"}

        sessdata = cookies.get("SESSDATA")
        bili_jct = cookies.get("bili_jct")
        dedeuserid = cookies.get("DedeUserID")

        if not all([sessdata, bili_jct, dedeuserid]):
            return {"success": False, "error": "Cookie 缺少必要字段（SESSDATA/bili_jct/DedeUserID）"}

        if dry_run:
            try:
                import requests
                resp = requests.get(
                    "https://api.bilibili.com/x/web-interface/nav",
                    cookies={"SESSDATA": sessdata, "bili_jct": bili_jct, "DedeUserID": dedeuserid},
                    timeout=10,
                )
                data = resp.json()
                if data.get("code") == 0:
                    user_info = data.get("data", {})
                    return {
                        "success": True,
                        "platform": "bilibili",
                        "uploaded": False,
                        "dry_run": True,
                        "username": user_info.get("uname", ""),
                        "uid": user_info.get("mid", ""),
                        "message": "B站 Cookie 有效（dry-run 模式，未实际上传）",
                    }
                else:
                    return {
                        "success": False,
                        "platform": "bilibili",
                        "error": f"Cookie 失效: {data.get('message', '')}",
                    }
            except Exception as e:
                return {"success": False, "error": f"B站 API 校验失败: {e}"}
        else:
            # 真实上传：调用 _publish_bilibili
            try:
                target = PublishTarget(
                    platform="bilibili",
                    title=title or video_p.stem,
                    video_path=video_p,
                    description=description,
                )
                result = self._publish_bilibili(target)
                return {
                    "success": result.get("status") == "success",
                    "platform": "bilibili",
                    "uploaded": True,
                    "published": result.get("status") == "success",
                    "dry_run": False,
                    "url": result.get("url"),
                    "error": result.get("error"),
                    "message": f"B站视频{'发布成功' if result.get('status') == 'success' else '发布失败'}",
                }
            except Exception as e:
                return {
                    "success": False,
                    "platform": "bilibili",
                    "error": f"B站上传失败: {e}",
                }

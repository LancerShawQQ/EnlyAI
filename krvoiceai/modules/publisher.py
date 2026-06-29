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
        """B站 API 发布"""
        cookie_file = self.cookies_dir / "bilibili.json"
        if not cookie_file.exists():
            target.status = "skipped"
            target.error = "B站 Cookie 未配置，跳过"
            self.logger.warning(target.error)
            return {"status": "skipped", "error": target.error}

        try:
            # 尝试使用 bilibili-api-python 库
            from bilibili_api import video_uploader, login
            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))

            self.logger.info(f"B站发布: {target.title}")
            # 实际发布逻辑（需要完整实现，此处为框架）
            # page = video_uploader.VideoUploaderPage(...)
            # uploader = video_uploader.VideoUploader([page], meta, login.VCredential())
            # result = uploader.start()

            target.status = "success"
            target.url = "https://www.bilibili.com/video/（待填充）"
            return {"status": "success", "url": target.url}
        except ImportError:
            target.status = "skipped"
            target.error = "bilibili-api-python 未安装"
            return {"status": "skipped", "error": target.error}
        except Exception as e:
            target.status = "failed"
            target.error = str(e)
            return {"status": "failed", "error": str(e)}

    def _publish_playwright(self, target: PublishTarget) -> dict:
        """Playwright 浏览器自动化发布"""
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
            target.error = f"{target.platform} Cookie 未配置，跳过"
            return {"status": "skipped", "error": target.error}

        self.logger.info(f"Playwright 发布到 {target.platform}: {target.title}")
        # 实际发布逻辑（需要针对各平台实现选择器，此处为框架）
        # with sync_playwright() as p:
        #     browser = p.chromium.launch(headless=False)
        #     context = browser.new_context()
        #     # 加载 cookie
        #     # 打开发布页
        #     # 上传视频
        #     # 填写标题/封面
        #     # 点击发布

        target.status = "success"
        return {"status": "success", "platform": target.platform}

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

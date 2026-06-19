"""对标文案提取模块

从参考视频 URL 提取口播文案。

流程：
1. yt-dlp 下载视频（仅音频流，节省带宽）
2. FunASR 转写为带标点文本
3. 文本清洗（去语气词、合并断句）

合规说明：仅支持用户手动提供链接，不做批量爬取；
仅提取文案用于参考改写，不直接复用原文。

mock 模式：不下载，返回模拟的口播文案。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.ffmpeg_utils import FFmpegRunner


# 语气词与无意义填充词（用于清洗）
FILLER_WORDS = [
    "嗯", "啊", "呃", "那个", "这个", "就是", "然后", "对吧",
    "你知道吗", "怎么说呢", "反正", "其实吧",
]


class ScriptExtractor(BaseModule):
    """对标文案提取模块"""

    name = "script_extract"
    requires_gpu = False

    def __init__(self, config=None, ffmpeg: FFmpegRunner | None = None):
        super().__init__(config)
        self.asr_provider = self.config.get("asr.provider", "mock")
        self.ffmpeg = ffmpeg or FFmpegRunner()
        self._ytdlp_available: Optional[bool] = None

    def setup(self) -> None:
        self._ytdlp_available = shutil.which("yt-dlp") is not None
        if not self._ytdlp_available:
            self.logger.warning("yt-dlp 未安装，将使用 mock 模式提取文案")
        self.logger.info(
            f"文案提取模块初始化 yt-dlp={'可用' if self._ytdlp_available else '不可用'}"
        )
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """从 ctx.reference_video_url 提取文案"""
        url = ctx.reference_video_url
        if not url:
            # 无参考视频 URL，跳过此步骤
            return ModuleResult(
                success=True,
                data={"skipped": True, "reason": "无参考视频 URL"},
            )

        try:
            if self._ytdlp_available and self.asr_provider == "funasr":
                text = self._extract_real(url, ctx.work_dir)
            else:
                text = self._extract_mock(url)

            text = self._clean_text(text)
            ctx.metadata["extracted_script"] = text
            # 提取的文案作为 input_script，供后续 script_write 仿写
            if not ctx.input_script:
                ctx.input_script = text

            return ModuleResult(
                success=True,
                data={
                    "script_text": text,
                    "source_url": url,
                    "char_count": len(text),
                    "mock": not (self._ytdlp_available and self.asr_provider == "funasr"),
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def extract(self, video_url: str, lang: str = "zh") -> str:
        """直接调用接口：从视频 URL 提取文案"""
        if self._ytdlp_available and self.asr_provider == "funasr":
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                text = self._extract_real(video_url, Path(tmp))
        else:
            text = self._extract_mock(video_url)
        return self._clean_text(text)

    def _extract_real(self, url: str, work_dir: Path) -> str:
        """真实提取：yt-dlp 下载 + FunASR 转写"""
        self.logger.info(f"下载视频音频: {url}")
        audio_path = work_dir / "ref_audio.wav"

        # yt-dlp 下载音频
        cmd = [
            "yt-dlp",
            "-x",                       # 仅提取音频
            "--audio-format", "wav",
            "-o", str(work_dir / "ref.%(ext)s"),
            "--no-playlist",
            "--no-warnings",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp 下载失败: {result.stderr[-300:]}")

        # 查找下载的音频文件
        audio_files = list(work_dir.glob("ref.*"))
        if not audio_files:
            raise RuntimeError("下载后未找到音频文件")
        audio_path = audio_files[0]

        # FunASR 转写
        self.logger.info(f"FunASR 转写: {audio_path}")
        from funasr import AutoModel
        model = AutoModel(
            model=self.config.get("asr.model", "paraformer-zh"),
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            disable_update=True,
        )
        result = model.generate(input=str(audio_path), batch_size_s=300)
        text = ""
        for res in result:
            text += res.get("text", "")
        return text

    def _extract_mock(self, url: str) -> str:
        """Mock 模式：返回模拟的口播文案

        根据平台特征生成不同主题的模拟文案。
        """
        self.logger.info(f"Mock 文案提取: {url}")
        # 根据域名推断平台
        if "douyin" in url or "iesdouyin" in url:
            topic = "抖音热门话题"
        elif "kuaishou" in url:
            topic = "快手热门内容"
        elif "bilibili" in url or "b23.tv" in url:
            topic = "B站知识分享"
        elif "youtube" in url or "youtu.be" in url:
            topic = "YouTube 教程"
        else:
            topic = "热门口播话题"

        return (
            f"今天和大家聊聊{topic}。"
            f"很多人对这个话题感兴趣，但真正搞明白的人不多。"
            f"我先讲一个核心观点，然后再展开说三个要点。"
            f"第一，要抓住本质，不要被表象迷惑。"
            f"第二，方法论很重要，照着做就能少走弯路。"
            f"第三，执行力是关键，光想不做等于零。"
            f"最后给大家一个建议，从今天开始行动起来。"
            f"觉得有用的话，点赞关注收藏三连，我们下期再见。"
        )

    def _clean_text(self, text: str) -> str:
        """清洗提取的文案"""
        if not text:
            return ""
        # 去除语气词
        for word in FILLER_WORDS:
            text = text.replace(word, "")
        # 合并多余空格
        text = re.sub(r"\s+", " ", text)
        # 合并连续标点
        text = re.sub(r"[，。！？]{2,}", lambda m: m.group(0)[0], text)
        # 去除首尾空白
        return text.strip()

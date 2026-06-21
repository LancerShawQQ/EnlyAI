"""对标文案提取模块

从参考视频 URL 提取口播文案。

流程：
1. yt-dlp 下载视频（仅音频流，节省带宽）
2. ASR 转写为带标点文本（支持 MiMo ASR / FunASR）
3. 文本清洗（去语气词、合并断句）

合规说明：仅支持用户手动提供链接，不做批量爬取；
仅提取文案用于参考改写，不直接复用原文。

mock 模式：不下载，返回模拟的口播文案。
"""
from __future__ import annotations

import base64
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx

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
        # MiMo ASR 配置
        self.mimo_api_base = self.config.get("asr.api_base", "")
        self.mimo_api_key = self.config.get("asr.api_key", "")
        self.mimo_model = self.config.get("asr.mimo_model", "mimo-v2.5-asr")
        self.timeout = self.config.get("asr.timeout", 120)

    def setup(self) -> None:
        self._ytdlp_available = shutil.which("yt-dlp") is not None
        if not self._ytdlp_available:
            self.logger.warning("yt-dlp 未安装，将使用 mock 模式提取文案")
        # 检查 ASR provider 是否可用
        if self.asr_provider == "mimo":
            if not self.mimo_api_key or not self.mimo_api_base:
                self.logger.warning("MiMo ASR 未配置 api_key/api_base，降级到 mock 模式")
                self.asr_provider = "mock"
            else:
                self.logger.info(f"文案提取模块初始化 yt-dlp={'可用' if self._ytdlp_available else '不可用'}, ASR=mimo/{self.mimo_model}")
        elif self.asr_provider == "funasr":
            self.logger.info(f"文案提取模块初始化 yt-dlp={'可用' if self._ytdlp_available else '不可用'}, ASR=funasr")
        else:
            self.logger.info(f"文案提取模块初始化 yt-dlp={'可用' if self._ytdlp_available else '不可用'}, ASR=mock")
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
            # yt-dlp 可用且 ASR provider 支持（mimo/funasr）时走真实提取
            use_real = self._ytdlp_available and self.asr_provider in ("funasr", "mimo")
            if use_real:
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
                    "mock": not use_real,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def extract(self, video_url: str, lang: str = "zh") -> str:
        """直接调用接口：从视频 URL 提取文案"""
        # 从分享文本中提取真实 URL（用户可能粘贴整段抖音分享文案）
        video_url = self._extract_url_from_text(video_url)
        if not video_url:
            raise ValueError("无法从输入中识别有效的视频链接，请粘贴包含抖音/快手/B站/YouTube 链接的内容")

        use_real = self._ytdlp_available and self.asr_provider in ("funasr", "mimo")
        if use_real:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    text = self._extract_real(video_url, Path(tmp))
                except Exception as e:
                    self.logger.warning(f"真实提取失败，降级到 mock 模式: {e}")
                    text = self._extract_mock(video_url)
        else:
            text = self._extract_mock(video_url)
        return self._clean_text(text)

    @staticmethod
    def _extract_url_from_text(text: str) -> str:
        """从用户输入的文本中提取视频 URL

        用户可能粘贴整段抖音分享文案，如：
        "2.87 复制打开抖音，看看【侃侃体育的作品】... https://v.douyin.com/5lPIfwzFtH0/ 03/29 ULw:/"
        需要从中提取出 https://v.douyin.com/5lPIfwzFtH0/
        """
        if not text:
            return ""
        text = text.strip()
        # 如果本身就是 URL，直接返回
        if re.match(r"^https?://", text):
            return text
        # 从文本中匹配 URL（支持抖音/快手/B站/YouTube短链）
        url_pattern = r"https?://[^\s<>\u4e00-\u9fa5]+"
        matches = re.findall(url_pattern, text)
        if matches:
            # 清理末尾可能的标点
            url = matches[0].rstrip(",.;!?，。；！？、）)】]")
            return url
        # 尝试匹配不带 https 的短链（如 v.douyin.com/xxx）
        short_pattern = r"(?:v\.douyin\.com|v\.kuaishou\.com|b23\.tv|youtu\.be)/[^\s<>\u4e00-\u9fa5]+"
        matches = re.findall(short_pattern, text)
        if matches:
            return "https://" + matches[0].rstrip(",.;!?，。；！？、）)】]")
        return ""

    def _extract_real(self, url: str, work_dir: Path) -> str:
        """真实提取：yt-dlp 下载 + ASR 转写（支持 MiMo / FunASR）"""
        self.logger.info(f"下载视频音频: {url}")

        # yt-dlp 下载音频
        cmd = [
            "yt-dlp",
            "-x",                       # 仅提取音频
            "--audio-format", "mp3",
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
        self.logger.info(f"下载完成: {audio_path.name} ({audio_path.stat().st_size // 1024}KB)")

        # 根据 provider 选择 ASR
        if self.asr_provider == "mimo":
            return self._transcribe_mimo(audio_path)
        else:
            return self._transcribe_funasr(audio_path)

    def _transcribe_mimo(self, audio_path: Path) -> str:
        """使用 MiMo ASR 转写音频为文本

        MiMo ASR 端点：{api_base}/chat/completions
        - 音频以 data URL 格式传入（data:audio/mp3;base64,...）
        - 不接受 text 部分（网关注入）
        - 返回识别文本在 choices[0].message.content
        """
        self.logger.info(f"MiMo ASR 转写: {audio_path.name}")

        audio_bytes = audio_path.read_bytes()
        ext = audio_path.suffix.lower().lstrip(".")
        mime = "audio/wav" if ext == "wav" else "audio/mp3"
        audio_b64 = base64.b64encode(audio_bytes).decode()
        data_url = f"data:{mime};base64,{audio_b64}"

        payload = {
            "model": self.mimo_model,
            "messages": [
                {"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": data_url, "format": ext or "mp3"}}
                ]}
            ],
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.mimo_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.mimo_api_base.rstrip('/')}/chat/completions"

        r = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            self.logger.warning("MiMo ASR 返回空内容，降级到 mock")
            return self._extract_mock(str(audio_path))

        self.logger.info(f"MiMo ASR 转写结果: {content[:100]}...")
        return content

    def _transcribe_funasr(self, audio_path: Path) -> str:
        """使用 FunASR 转写音频为文本"""
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

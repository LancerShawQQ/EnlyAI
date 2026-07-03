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

# URL 边界排除字符集：URL 中不应出现的字符（空格、<>、中文、各类引号/包裹符）
# 关键：含反引号 `、单双引号、中文引号「」『』、方括号【】[]、括号（）()
# 修复历史 Bug：抖音分享文本常以反引号包围 URL，旧正则未排除反引号导致 URL 末尾带 `
_URL_BOUNDARY_CHARS = r"`'\"\u300c\u300d\u300e\u300f\u3010\u3011\[\]\uff08\uff09\(\)"

# URL 末尾清理字符集：strip 这些可能粘在 URL 末尾的标点
_URL_TRAILING_CHARS = ",.;!?，。；！？、）)】」』`'\""

# 描述末尾清理字符集：含省略号、反引号、引号等包裹符（修复反引号边界 Bug）
_DESC_TRAILING_CHARS = "….;；，,。 \n`'\"」』"


def _build_url_pattern(prefix: str = r"https?://") -> str:
    """构建 URL 匹配正则：prefix + 非边界字符序列"""
    return prefix + r"[^\s<>\u4e00-\u9fa5" + _URL_BOUNDARY_CHARS + r"]+"


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
        # yt-dlp cookies 文件路径（抖音/快手反爬必需，Netscape 格式 .txt）
        self.cookies_file = self.config.get("asr.cookies_file", "")
        # yt-dlp 自动从本机浏览器读取 cookies（用户无感知，无需手动上传）
        # 支持 chrome/edge/firefox 等，优先级高于 cookies_file
        self.cookies_from_browser = self.config.get("asr.cookies_from_browser", "")

    def setup(self) -> None:
        # yt-dlp 检测：优先命令行，其次 Python 模块
        self._ytdlp_available = shutil.which("yt-dlp") is not None
        if not self._ytdlp_available:
            try:
                import yt_dlp  # noqa: F401
                self._ytdlp_available = True
                self._ytdlp_as_module = True
            except ImportError:
                self._ytdlp_as_module = False
        else:
            self._ytdlp_as_module = False
        if not self._ytdlp_available:
            self.logger.warning("yt-dlp 未安装，视频链接提取将不可用（本地文件提取仍可用）")
        # 检查 ASR provider 是否可用
        if self.asr_provider == "mimo":
            if not self.mimo_api_key or not self.mimo_api_base:
                self.logger.warning("MiMo ASR 未配置 api_key/api_base，降级到 mock 模式")
                self.asr_provider = "mock"
            else:
                self.logger.info(f"文案提取模块初始化 yt-dlp={'可用' if self._ytdlp_available else '不可用'}, ASR=mimo/{self.mimo_model}")
        elif self.asr_provider == "funasr":
            self.logger.info(f"文案提取模块初始化 yt-dlp={'可用' if self._ytdlp_available else '不可用'}, ASR=funasr")
        elif self.asr_provider == "whisper_local":
            # whisper_local 用于本地文件转写（不依赖 yt-dlp）
            try:
                import faster_whisper  # noqa: F401
                self.logger.info(f"文案提取模块初始化 yt-dlp={'可用' if self._ytdlp_available else '不可用'}, ASR=whisper_local")
            except ImportError:
                self.logger.warning("faster-whisper 未安装，本地文件转写将降级 mock。安装：pip install -e \".[local]\"")
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
            # 复用 extract() 的完整降级链：
            #   Playwright 网页抓取 → yt-dlp+ASR → web_desc → 分享文本 → mock
            # 避免 _extract_real 失败时直接返回失败（抖音反爬导致 yt-dlp 经常失败）
            text = self.extract(url)
            degraded = getattr(self, "_last_extract_degraded", False)

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
                    "mock": degraded,
                    "degraded": degraded,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def extract(self, video_url: str, lang: str = "zh") -> str:

        # === 提取结果缓存（按URL hash，避免重复提取耗时3分钟）===
        import hashlib as _hashlib
        _url_hash = _hashlib.md5(video_url.encode()).hexdigest()[:12]
        _cache_dir = Path(getattr(self, 'work_dir', Path('.'))) / '.extract_cache'
        _cache_file = _cache_dir / f'{_url_hash}.txt'
        if _cache_file.exists():
            _age = time.time() - _cache_file.stat().st_mtime
            if _age < 86400:  # 24小时内的缓存有效
                cached = _cache_file.read_text(encoding='utf-8').strip()
                if cached:
                    self.logger.info(f'命中提取缓存（URL hash={_url_hash}, {_age/3600:.1f}h前缓存）')
                    return cached
        """直接调用接口：从视频/文章 URL 或本地文件提取文案

        支持三类输入：
        1. 本地视频/音频文件（路径存在）：FFmpeg 提取音频 + ASR 转写
        2. 视频链接（抖音/快手/B站/YouTube）：yt-dlp 下载音频 + ASR 转写
        3. 文章链接（腾讯新闻/微信公众号/新浪新闻等）：requests 抓取网页正文
        """
        # === 降级标记（供调用方判断是否为降级文案，非真实 ASR 转写） ===
        self._last_extract_degraded = False
        # === 优先检测本地文件 ===
        cleaned_input = video_url.strip().strip('"').strip("'")
        local_path = Path(cleaned_input)
        if local_path.exists() and local_path.is_file():
            return self._extract_from_local_file(local_path)

        # 从分享文本中提取真实 URL（用户可能粘贴整段抖音分享文案）
        video_url = self._extract_url_from_text(video_url)
        if not video_url:
            raise ValueError("无法从输入中识别有效的视频链接或本地文件，请粘贴包含抖音/快手/B站/YouTube 链接的内容，或提供本地视频文件路径")

        # 判断是视频链接还是文章链接
        is_video = self._is_video_url(video_url)

        if is_video:
            # === 优先：Playwright 网页抓取（绕过 JS 挑战，提取 desc + 视频 URL）===
            web_desc, video_dl_url = self._extract_from_web_page(video_url, cleaned_input)

            # 如果拿到视频 URL 且 ASR 可用 → 下载视频音频 + ASR 转写完整口播文案
            asr_capable = self.asr_provider in ("funasr", "mimo", "whisper_local")
            if video_dl_url and asr_capable:
                import tempfile
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        text = self._download_and_transcribe(video_dl_url, Path(tmp))
                        if text and len(text) >= 10:
                            self.logger.info(f"视频下载+ASR 转写成功: {len(text)} 字")
                            return self._clean_text(text)
                    except Exception as e:
                        self.logger.warning(f"视频下载+ASR 转写失败: {e}")

            # Playwright 没拿到 video_url → yt-dlp + ASR 重型兜底（抖音可能需要 cookies）
            use_real = self._ytdlp_available and asr_capable
            if use_real:
                import tempfile
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        text = self._extract_real(video_url, Path(tmp))
                    except Exception as e:
                        self.logger.warning(f"视频音频下载/转写失败: {e}")
                        # 降级链：优先用 Playwright 提取的 web_desc（可能是完整描述）
                        if web_desc and len(web_desc) >= 10:
                            self.logger.info(f"使用网页抓取文案（降级）: {len(web_desc)} 字")
                            text = web_desc
                            self._last_extract_degraded = True
                        else:
                            desc = self._extract_desc_from_share_text(cleaned_input)
                            if desc:
                                self.logger.info(f"已从分享文本提取文案描述: {len(desc)} 字")
                                text = desc
                                self._last_extract_degraded = True
                            else:
                                try:
                                    text = self._extract_article(video_url)
                                except Exception as e2:
                                    self.logger.warning(f"文章提取也失败: {e2}")
                                    raise RuntimeError(
                                        f"无法提取文案（网页抓取与视频下载均失败）。"
                                        f"请直接在第①步手动输入文案，或粘贴抖音分享文本。"
                                    )
            else:
                # yt-dlp 或 ASR 不可用：优先用 Playwright 提取的 web_desc，再降级到分享文本/mock
                if web_desc and len(web_desc) >= 10:
                    self.logger.info(f"使用网页抓取文案: {len(web_desc)} 字")
                    text = web_desc
                    self._last_extract_degraded = True
                else:
                    desc = self._extract_desc_from_share_text(cleaned_input)
                    if desc:
                        self.logger.info(f"yt-dlp/ASR 不可用，使用分享文本文案描述: {len(desc)} 字")
                        text = desc
                        self._last_extract_degraded = True
                    else:
                        text = self._extract_mock(video_url)
        else:
            # 文章链接：直接抓取网页正文
            try:
                text = self._extract_article(video_url)
            except Exception as e:
                self.logger.warning(f"文章提取失败，降级到 mock: {e}")
                text = self._extract_mock(video_url)
        # 写入缓存
        try:
            _cache_dir.mkdir(parents=True, exist_ok=True)
            _cache_file.write_text(text, encoding='utf-8')
            self.logger.info(f'提取结果已缓存（URL hash={_url_hash}）')
        except Exception:
            pass
        return self._clean_text(text)

    def _extract_from_local_file(self, path: Path) -> str:
        """从本地视频/音频文件提取文案：FFmpeg 提取音频 + ASR 转写"""
        self.logger.info(f"从本地文件提取文案: {path.name}")

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # 提取音频为 wav，并做音量归一化（loudnorm）+ 提升低音量
            # 原因：手机录制视频常出现 mean_volume < -40dB 的极低音量，
            # whisper 在此条件下无法识别语音。loudnorm 标准化到 -16dB 响度。
            audio_path = tmp_path / "audio.wav"
            try:
                # 先提取原始音频
                raw_audio = tmp_path / "raw.wav"
                self.ffmpeg.convert_audio(path, raw_audio, sample_rate=16000, channels=1)
                # 再做音量归一化（dynaudnorm 自适应增益 + 提升整体音量）
                import subprocess
                norm_cmd = [
                    self.ffmpeg.ffmpeg, "-y", "-i", str(raw_audio),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=16000",
                    "-ac", "1",
                    str(audio_path),
                ]
                r = subprocess.run(norm_cmd, capture_output=True, text=True)
                if r.returncode != 0 or not audio_path.exists():
                    # loudnorm 失败则用原始音频
                    self.logger.warning(f"loudnorm 失败，用原始音频: {r.stderr[-200:]}")
                    audio_path = raw_audio
                else:
                    self.logger.info("音频已归一化（loudnorm -16dB）")
            except Exception as e:
                raise RuntimeError(f"音频提取失败（{path.name}）: {e}")

            # 根据 provider 转写
            if self.asr_provider == "mimo":
                return self._clean_text(self._transcribe_mimo(audio_path))
            elif self.asr_provider == "funasr":
                try:
                    return self._clean_text(self._transcribe_funasr(audio_path))
                except ImportError:
                    self.logger.warning("FunASR 未安装，降级到 whisper/mock")
                    return self._clean_text(self._transcribe_local(audio_path))
            elif self.asr_provider == "whisper_local":
                return self._clean_text(self._transcribe_local(audio_path))
            else:
                self.logger.warning(f"ASR provider={self.asr_provider} 不支持转写，降级 mock")
                return self._clean_text(self._extract_mock(str(path)))

    def _transcribe_local(self, audio_path: Path) -> str:
        """使用 faster-whisper 本地转写（CPU int8）

        用于本地文件文案提取；whisper_local provider 不可用时降级 mock。
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            self.logger.warning("faster-whisper 未安装，文案提取降级 mock")
            return self._extract_mock(str(audio_path))

        whisper_cfg = self.config.get("asr.whisper", {}) or {}
        model_size = whisper_cfg.get("model_size", "small")
        device = whisper_cfg.get("device", "cpu")
        compute_type = whisper_cfg.get("compute_type", "int8")
        beam_size = whisper_cfg.get("beam_size", 5)
        # 热词：提示 whisper 关注特定词汇，减少专有名词/术语识别错误
        hotwords = whisper_cfg.get("hotwords", "")
        download_root = whisper_cfg.get("download_root", "") or None

        self.logger.info(
            f"faster-whisper 本地转写: {audio_path.name} model={model_size} beam={beam_size}"
        )
        model = WhisperModel(
            model_size, device=device, compute_type=compute_type,
            download_root=download_root,
        )
        # initial_prompt 引导 whisper 输出简体中文 + 标点 + 热词（默认 small 模型倾向繁体）
        prompt = "以下是普通话的句子，使用简体中文和正确的标点符号。"
        if hotwords:
            prompt += f" 关键词：{hotwords}"
        segments, _ = model.transcribe(
            str(audio_path), language="zh", vad_filter=True,
            beam_size=beam_size,
            initial_prompt=prompt,
            condition_on_previous_text=False,  # 避免幻觉扩散
            no_speech_threshold=0.6,            # 静音过滤阈值
            compression_ratio_threshold=2.4,   # 压缩比阈值（防乱码）
        )
        text = "".join(seg.text for seg in segments).strip()
        self.logger.info(f"转写完成: {len(text)} 字, 预览: {text[:80]}")
        return text

    @staticmethod
    def _is_video_url(url: str) -> bool:
        """判断 URL 是否为视频链接"""
        video_domains = (
            "douyin.com", "iesdouyin.com", "kuaishou.com",
            "bilibili.com", "b23.tv", "youtube.com", "youtu.be",
            "weibo.com", "xiaohongshu.com",
        )
        return any(d in url for d in video_domains)

    def _extract_article(self, url: str) -> str:
        """从新闻/文章页面提取正文文本

        支持：腾讯新闻、微信公众号、新浪新闻、网易新闻、知乎专栏等
        """
        self.logger.info(f"提取文章正文: {url}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        r = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        r.raise_for_status()
        html = r.text

        # 提取标题
        title = ""
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html)
        if title_match:
            title = title_match.group(1).strip()
            # 清理常见后缀
            title = re.sub(r"\s*[-_|]\s*腾讯新闻.*$", "", title)
            title = re.sub(r"\s*[-_|]\s*新浪.*$", "", title)
            title = re.sub(r"\s*[-_|]\s*网易.*$", "", title)

        # 提取正文段落：<p> 标签中长度 > 30 的文本
        # 先移除 script/style 标签内容
        clean_html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        clean_html = re.sub(r"<style[^>]*>.*?</style>", "", clean_html, flags=re.DOTALL | re.IGNORECASE)
        # 提取所有 <p> 标签内容
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", clean_html, flags=re.DOTALL | re.IGNORECASE)
        # 清理 HTML 标签，保留纯文本
        body_parts = []
        for p in paragraphs:
            # 移除内部 HTML 标签
            text = re.sub(r"<[^>]+>", "", p).strip()
            # 过滤短文本（导航、广告等）
            if len(text) >= 30:
                body_parts.append(text)

        # 如果 <p> 标签提取失败，尝试 meta description
        if not body_parts:
            desc_match = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.IGNORECASE)
            if desc_match:
                body_parts.append(desc_match.group(1).strip())

        if not body_parts:
            raise RuntimeError("无法从页面提取正文内容")

        # 组合标题 + 正文
        result = title + "\n" + "\n".join(body_parts) if title else "\n".join(body_parts)
        self.logger.info(f"文章提取完成: {len(result)} 字, {len(body_parts)} 段")
        return result

    @staticmethod
    def _extract_url_from_text(text: str) -> str:
        """从用户输入的文本中提取视频 URL

        用户可能粘贴整段抖音分享文案，如：
        "2.87 复制打开抖音，看看【侃侃体育的作品】... https://v.douyin.com/5lPIfwzFtH0/ 03/29 ULw:/"
        需要从中提取出 https://v.douyin.com/5lPIfwzFtH0/

        支持 URL 被反引号/引号/括号包围的场景：
        "看看【xx的作品】文案... `https://v.douyin.com/xxx/` anq:/ :1pm"
        """
        if not text:
            return ""
        text = text.strip()
        # 从文本中匹配 URL（支持抖音/快手/B站/YouTube短链）
        # 边界排除反引号/引号/括号等包裹符，避免 URL 末尾带包裹符
        # 统一走 findall：能正确处理纯 URL、URL+口令后缀、被包裹符包围的 URL
        url_pattern = _build_url_pattern(r"https?://")
        matches = re.findall(url_pattern, text)
        if matches:
            return matches[0].rstrip(_URL_TRAILING_CHARS)
        # 尝试匹配不带 https 的短链（如 v.douyin.com/xxx）
        short_pattern = _build_url_pattern(r"(?:v\.douyin\.com|v\.kuaishou\.com|b23\.tv|youtu\.be)/")
        matches = re.findall(short_pattern, text)
        if matches:
            return "https://" + matches[0].rstrip(_URL_TRAILING_CHARS)
        return ""

    @staticmethod
    def _extract_desc_from_share_text(text: str) -> str:
        """从抖音/快手分享文本中提取视频文案描述（最可靠，无需下载）

        抖音分享格式：
        "1.25 复制打开抖音，看看【风芒新闻的作品】深圳一三甲医院涉嫌伪造病历... https://v.douyin.com/xxx/"

        快手/B站分享也含描述。这是最可靠的方式，因为抖音/快手有强力反爬，
        yt-dlp 经常因 cookie 问题无法下载。返回空串表示未提取到。
        """
        if not text:
            return ""
        text = text.strip()
        # URL 前置边界：允许空格/反引号/引号等包裹符出现在 URL 前
        # 修复历史 Bug：抖音分享文本常以反引号包围 URL，旧正则只允许 \s+ 导致描述吞掉整个 URL
        _url_prefix_boundary = r"(?:[\s`'\"\u300c\u300d\u300e\u300f]*https?://|$)"
        # 抖音：【作者的作品】文案内容 https://...
        m = re.search(r"看看【(.+?)】(.+?)" + _url_prefix_boundary, text)
        if m:
            desc = m.group(2).strip()
            # 去掉末尾省略号或标点（含反引号等包裹符）
            desc = desc.rstrip(_DESC_TRAILING_CHARS)
            if len(desc) >= 4:
                return desc
        # 快手：复制打开快手...文案 https://...
        m = re.search(r"复制打开快[手眼][，,]?\s*(.+?)" + _url_prefix_boundary, text)
        if m:
            desc = m.group(1).strip().rstrip(_DESC_TRAILING_CHARS)
            if len(desc) >= 4:
                return desc
        # 通用：URL 之前的中文描述（去掉前缀"复制打开xxx"）
        url_pos = text.find("http")
        if url_pos > 10:
            prefix = text[:url_pos].strip()
            # 去掉常见的分享前缀
            prefix = re.sub(r"^[\d.]+\s*复制打开[^，,]*[，,]?\s*", "", prefix)
            prefix = re.sub(r"^看看【[^】]*】\s*", "", prefix)
            prefix = prefix.strip().rstrip(_DESC_TRAILING_CHARS)
            if len(prefix) >= 4:
                return prefix
        return ""

    def _extract_real(self, url: str, work_dir: Path) -> str:
        """真实提取：yt-dlp 下载 + ASR 转写（支持 MiMo / FunASR / whisper_local）"""
        self.logger.info(f"下载视频音频: {url}")

        # yt-dlp 下载音频（优先 Python API，其次命令行）
        output_template = str(work_dir / "ref.%(ext)s")
        downloaded = self._ytdlp_download_audio(url, output_template)
        if not downloaded:
            raise RuntimeError("yt-dlp 下载失败或未找到音频文件")

        audio_path = downloaded
        self.logger.info(f"下载完成: {audio_path.name} ({audio_path.stat().st_size // 1024}KB)")

        # 音量归一化（部分平台下载的音频音量偏低）
        norm_audio = work_dir / "ref_norm.wav"
        try:
            import subprocess
            r = subprocess.run(
                [self.ffmpeg.ffmpeg, "-y", "-i", str(audio_path),
                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                 "-ar", "16000", "-ac", "1", str(norm_audio)],
                capture_output=True, text=True,
            )
            if r.returncode == 0 and norm_audio.exists():
                audio_path = norm_audio
        except Exception:
            pass

        # 根据 provider 选择 ASR
        if self.asr_provider == "mimo":
            return self._transcribe_mimo(audio_path)
        elif self.asr_provider == "whisper_local":
            return self._transcribe_local(audio_path)
        else:
            return self._transcribe_funasr(audio_path)

    # ============ 网页抓取（轻量，无需下载视频/无需用户上传 cookies）============

    # 真实浏览器 UA（避免被识别为爬虫）
    _BROWSER_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    def _extract_from_web_page(self, url: str, share_text: str = "") -> tuple[str, str]:
        """从视频分享页抓取文案 + 视频 URL（用户无感知）

        Returns: (desc, video_dl_url)，失败返回 ("", "")
        """
        try:
            if "douyin.com" in url or "iesdouyin" in url:
                return self._fetch_douyin_share(url, share_text)
            if "kuaishou.com" in url:
                return self._fetch_kuaishou_share(url, share_text), ""
            if "bilibili.com" in url or "b23.tv" in url:
                return self._fetch_bilibili_share(url, share_text), ""
        except Exception as e:
            self.logger.warning(f"网页抓取失败 ({url[:60]}): {e}")
        return "", ""

    def _fetch_douyin_share(self, url: str, share_text: str = "") -> tuple[str, str]:
        """抖音分享页抓取：Playwright 无头浏览器绕过 JS 挑战（用户无感知）

        Returns: (desc, video_dl_url)
        """
        # 优先：Playwright 无头浏览器（最可靠，绕过所有 JS 挑战）
        # 重试机制：偶发页面加载超时，重试一次提升成功率
        desc, video_url = "", ""
        for attempt in (1,):  # 单次尝试，失败直接降级（避免翻倍耗时）
            desc, video_url = self._fetch_with_playwright(url, "douyin")
            if (desc and len(desc) >= 10) or video_url:
                self.logger.info(f"抖音 Playwright 提取成功（第{attempt}次）: desc={len(desc)}字, video_url={'有' if video_url else '无'}")
                break
            self.logger.warning(f"抖音 Playwright 第{attempt}次尝试未提取到内容，{'重试' if attempt == 1 else '降级'}")
        if desc and len(desc) >= 10:
            return desc, video_url

        # 降级：httpx 解析（可能被 JS 挑战拦截，作为兜底尝试）
        headers = {
            "User-Agent": self._BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.douyin.com/",
        }
        aweme_id = ""
        try:
            r = httpx.get(url, headers=headers, timeout=15, follow_redirects=False)
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("location", "")
                am = re.search(r"/video/(\d+)", loc)
                if am:
                    aweme_id = am.group(1)
        except Exception as e:
            self.logger.debug(f"抖音短链解析失败: {e}")

        html = ""
        if aweme_id:
            try:
                share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
                r2 = httpx.get(share_url, headers=headers, timeout=15, follow_redirects=True)
                html = r2.text
            except Exception as e:
                self.logger.debug(f"iesdouyin 分享页获取失败: {e}")

        http_desc, subtitle_url, _ = self._parse_douyin_html(html) if html else ("", "", "")

        if subtitle_url:
            sub_text = self._download_subtitle(subtitle_url, headers)
            if sub_text and len(sub_text) >= 10:
                self.logger.info(f"抖音字幕提取成功: {len(sub_text)} 字")
                return sub_text, ""

        if http_desc and len(http_desc) >= 20:
            self.logger.info(f"抖音 desc 提取成功: {len(http_desc)} 字")
            return http_desc, ""

        return "", ""

    def _fetch_with_playwright(self, url: str, platform: str = "douyin") -> tuple[str, str]:
        """用 Playwright 无头浏览器渲染页面并提取文案 + 视频 URL（用户无感知）

        Returns: (desc, video_dl_url)
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.warning("Playwright 未安装，跳过无头浏览器方案。安装: pip install playwright")
            return "", ""

        # 先解析 aweme_id（用于直接访问分享页，避免短链超时）
        aweme_id = ""
        try:
            headers = {"User-Agent": self._BROWSER_UA}
            # follow_redirects=True 跟随短链重定向，从最终 URL 提取 aweme_id
            r = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
            am = re.search(r"/video/(\d+)", str(r.url))
            if am:
                aweme_id = am.group(1)
        except Exception:
            pass

        share_url = url
        if aweme_id:
            share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"

        try:
            with sync_playwright() as p:
                # 尝试多个浏览器通道：系统已装的优先（Edge/Chrome），最后 Chromium
                browser = None
                launch_err = None
                for _ch in ("msedge", "chrome"):
                    try:
                        browser = p.chromium.launch(channel=_ch, headless=True)
                        self.logger.info(f"Playwright 浏览器: {_ch}")
                        break
                    except Exception as e:
                        launch_err = e
                if browser is None:
                    try:
                        browser = p.chromium.launch(headless=True)
                        self.logger.info("Playwright 浏览器: chromium")
                    except Exception as e:
                        raise RuntimeError(f"无可用浏览器通道: {e}") from launch_err

                context = browser.new_context(
                    user_agent=self._BROWSER_UA,
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()

                # 监听网络请求，捕获实际视频流 URL（douyinvod.com）
                captured_video_urls = []
                def _capture_video(response):
                    u = response.url
                    if "douyinvod.com" in u or "video/tos" in u:
                        captured_video_urls.append(u)
                page.on("response", _capture_video)

                self.logger.info(f"Playwright 渲染: {share_url}")
                try:
                    try:
                        page.goto(share_url, wait_until="domcontentloaded", timeout=20000)
                        page.wait_for_timeout(1500)
                    except Exception as e:
                        self.logger.debug(f"Playwright 页面加载超时: {str(e)[:80]}")

                    # 滚动 + play() 触发视频懒加载（抖音视频默认不预加载流）
                    try:
                        page.evaluate('window.scrollTo(0, 300)')
                        page.wait_for_timeout(500)
                        page.evaluate(
                            'var v=document.querySelector("video");'
                            'if(v){v.muted=true; v.play().catch(function(){});}'
                        )
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        self.logger.debug(f"触发视频加载失败: {str(e)[:80]}")

                    # 提取文案：title 和 meta description
                    title = page.title() or ""
                    meta_desc = page.evaluate(
                        'document.querySelector("meta[name=description]")?.getAttribute("content") || ""'
                    )

                    desc = ""
                    if title:
                        desc = re.sub(r"\s*-\s*抖音\s*$", "", title).strip()
                        desc = re.sub(r"#[\w]+$", "", desc).strip()
                    if meta_desc and len(meta_desc) > len(desc):
                        desc = re.sub(r"\s*-\s*.*?于\d+.*?发布在抖音.*$", "", meta_desc).strip()
                        desc = re.sub(r"#[\w]+$", "", desc).strip()

                    # 提取视频 URL：优先从网络请求捕获（douyinvod.com），其次从 video.currentSrc，最后从 RENDER_DATA
                    video_dl_url = ""
                    if captured_video_urls:
                        video_dl_url = captured_video_urls[0]
                        self.logger.info(f"Playwright 捕获视频流: {len(captured_video_urls)} 个")
                    else:
                        cur = page.evaluate('document.querySelector("video")?.currentSrc || ""')
                        if cur and ("douyinvod.com" in cur or "video/tos" in cur):
                            video_dl_url = cur
                            self.logger.info("从 video.currentSrc 提取视频 URL")

                    # 从 RENDER_DATA 提取 desc 和 video URL（兜底，抖音页面数据源）
                    render_data = page.evaluate(
                        'document.getElementById("RENDER_DATA")?.textContent || ""'
                    )
                    if render_data:
                        from urllib.parse import unquote
                        decoded = unquote(render_data)
                        # 提取 desc
                        if not desc or len(desc) < 20:
                            dm = re.search(r'"desc":"((?:[^"\\]|\\.)*)"', decoded)
                            if dm:
                                try:
                                    rd_desc = dm.group(1).encode().decode("unicode_escape", errors="ignore")
                                except Exception:
                                    rd_desc = dm.group(1)
                                if rd_desc and len(rd_desc) > len(desc):
                                    desc = rd_desc
                        # 兜底提取视频 URL（网络捕获失败时）
                        if not video_dl_url:
                            vm = re.search(
                                r'(https?://[^"\s\\]+\.douyinvod\.com/[^"\s\\]+)',
                                decoded,
                            )
                            if vm:
                                video_dl_url = vm.group(1)
                                self.logger.info("从 RENDER_DATA 提取视频 URL")

                    if desc and len(desc) >= 10:
                        self.logger.info(f"Playwright 提取: desc={len(desc)}字, video_url={'有' if video_dl_url else '无'}")
                        return desc, video_dl_url
                    elif video_dl_url:
                        self.logger.info(f"Playwright 仅提取到视频 URL（无文案），将做 ASR 转写")
                        return "", video_dl_url
                    self.logger.warning(f"Playwright 渲染完成但未提取到内容: title={len(title)}字, meta={len(meta_desc)}字, caps={len(captured_video_urls)}")
                finally:
                    # 确保 browser 关闭，避免 Edge 残留进程影响后续启动
                    try:
                        browser.close()
                    except Exception:
                        pass
        except Exception as e:
            self.logger.warning(f"Playwright 渲染失败: {str(e)[:120]}")
        return "", ""

    def _download_and_transcribe(self, video_url: str, work_dir: Path) -> str:
        """下载视频 → FFmpeg 提取音频 → ASR 转写完整口播文案

        用 httpx 下载视频（无需 yt-dlp），FFmpeg 提取音频，ASR 转写。
        """
        import tempfile
        video_path = work_dir / "ref_video.mp4"
        audio_path = work_dir / "audio.wav"

        # 下载视频
        self.logger.info(f"下载视频: {video_url[:80]}...")
        headers = {
            "User-Agent": self._BROWSER_UA,
            "Referer": "https://www.douyin.com/",
        }
        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            with client.stream("GET", video_url) as resp:
                resp.raise_for_status()
                with open(video_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
        self.logger.info(f"视频下载完成: {video_path.stat().st_size} bytes")

        # FFmpeg 提取音频 + 音量归一化
        raw_audio = work_dir / "raw.wav"
        self.ffmpeg.convert_audio(video_path, raw_audio, sample_rate=16000, channels=1)
        import subprocess
        norm_cmd = [
            self.ffmpeg.ffmpeg, "-y", "-i", str(raw_audio),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=16000",
            "-ac", "1", str(audio_path),
        ]
        r = subprocess.run(norm_cmd, capture_output=True, text=True)
        if r.returncode != 0 or not audio_path.exists():
            self.logger.warning(f"loudnorm 失败，用原始音频: {r.stderr[-200:]}")
            audio_path = raw_audio
        else:
            self.logger.info("音频已归一化（loudnorm -16dB）")

        # ASR 转写
        if self.asr_provider == "mimo":
            return self._transcribe_mimo(audio_path)
        elif self.asr_provider == "funasr":
            try:
                return self._transcribe_funasr(audio_path)
            except ImportError:
                self.logger.warning("FunASR 未安装，降级到 whisper")
                return self._transcribe_local(audio_path)
        elif self.asr_provider == "whisper_local":
            return self._transcribe_local(audio_path)
        else:
            self.logger.warning(f"ASR provider={self.asr_provider} 不支持，降级 mock")
            return self._extract_mock(str(video_path))

    def _parse_douyin_html(self, html: str) -> tuple[str, str, str]:
        """从抖音分享页 HTML 解析 desc 和字幕 URL

        抖音分享页内嵌 JSON 有两种位置：
        1. <script id="RENDER_DATA" type="application/json">{URL编码的JSON}</script>
        2. window._ROUTER_DATA = {JSON}
        3. 直接 aweme_id 在 URL 或 meta 中
        Returns: (desc, subtitle_url, aweme_id)
        """
        desc, subtitle_url, aweme_id = "", "", ""

        # 方式1：RENDER_DATA（URL编码）
        m = re.search(r'id="RENDER_DATA"[^>]*>([^<]+)</script>', html)
        if m:
            try:
                from urllib.parse import unquote
                data = unquote(m.group(1))
                # 提取 desc
                dm = re.search(r'"desc"\s*:\s*"((?:[^"\\]|\\.)*)"', data)
                if dm:
                    desc = dm.group(1).encode().decode("unicode_escape", errors="ignore")
                # 提取字幕 URL
                sm = re.search(r'"subtitle"\s*:\s*\{[^}]*"url"\s*:\s*"((?:[^"\\]|\\.)*)"', data)
                if sm:
                    subtitle_url = sm.group(1).encode().decode("unicode_escape", errors="ignore")
                # 提取 aweme_id
                am = re.search(r'"aweme_id"\s*:\s*"(\d+)"', data)
                if am:
                    aweme_id = am.group(1)
            except Exception as e:
                self.logger.debug(f"解析 RENDER_DATA 失败: {e}")

        # 方式2：window._ROUTER_DATA
        if not desc:
            m = re.search(r'_ROUTER_DATA\s*=\s*(\{.+?\})\s*</script>', html, re.DOTALL)
            if m:
                try:
                    import json as _json
                    data = _json.loads(m.group(1))
                    # 嵌套结构 loaderData.video_{id}.videoInfo
                    for v in data.get("loaderData", {}).values():
                        info = v.get("videoInfo") or v
                        if isinstance(info, dict):
                            if not desc and info.get("desc"):
                                desc = info["desc"]
                            sub = info.get("subtitle") or {}
                            if isinstance(sub, dict) and sub.get("url") and not subtitle_url:
                                subtitle_url = sub["url"]
                            if info.get("aweme_id") and not aweme_id:
                                aweme_id = info["aweme_id"]
                            if desc:
                                break
                except Exception as e:
                    self.logger.debug(f"解析 _ROUTER_DATA 失败: {e}")

        # 方式3：meta og:title 兜底拿 desc
        if not desc:
            tm = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
            if tm:
                desc = tm.group(1).strip()

        # 清理 desc 末尾的分享后缀
        if desc:
            desc = re.sub(r"\s*#[^#]+$", "", desc).strip()  # 去话题标签
            desc = desc.rstrip("….").strip()
        return desc, subtitle_url, aweme_id

    def _fetch_kuaishou_share(self, url: str, share_text: str = "") -> str:
        """快手分享页抓取"""
        headers = {
            "User-Agent": self._BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.kuaishou.com/",
        }
        r = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        html = r.text
        # 快手 meta og:description
        m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html)
        if m and len(m.group(1)) >= 20:
            return m.group(1).strip()
        if share_text:
            return self._extract_desc_from_share_text(share_text) or ""
        return ""

    def _fetch_bilibili_share(self, url: str, share_text: str = "") -> str:
        """B站分享页抓取：B站有开放 API 可拿字幕"""
        headers = {
            "User-Agent": self._BROWSER_UA,
            "Accept": "application/json",
            "Referer": "https://www.bilibili.com/",
        }
        # 解析 BV 号
        bvm = re.search(r"(BV[\w]+)", url)
        if bvm:
            bvid = bvm.group(1)
            try:
                # B站 web API 获取视频信息
                info_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
                r = httpx.get(info_url, headers=headers, timeout=15)
                data = r.json()
                desc = data.get("data", {}).get("desc", "")
                if desc and len(desc) >= 20:
                    self.logger.info(f"B站 desc 提取: {len(desc)} 字")
                    return desc
                # 尝试获取字幕
                cid = data.get("data", {}).get("cid")
                if cid:
                    sub_text = self._fetch_bilibili_subtitle(cid, headers)
                    if sub_text:
                        return sub_text
            except Exception as e:
                self.logger.debug(f"B站 API 失败: {e}")
        # 兜底：分享文本
        if share_text:
            return self._extract_desc_from_share_text(share_text) or ""
        return ""

    def _fetch_bilibili_subtitle(self, cid: str, headers: dict) -> str:
        """获取 B站字幕（subtitle API）"""
        try:
            sub_url = f"https://api.bilibili.com/x/player/v2?cid={cid}"
            r = httpx.get(sub_url, headers=headers, timeout=15)
            data = r.json()
            subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
            for sub in subtitles:
                url = sub.get("subtitle_url", "")
                if url:
                    if url.startswith("//"):
                        url = "https:" + url
                    return self._download_subtitle(url, headers)
        except Exception as e:
            self.logger.debug(f"B站字幕获取失败: {e}")
        return ""

    def _download_subtitle(self, url: str, headers: dict) -> str:
        """下载字幕文件（SRT/JSON/VTT）并提取纯文本

        抖音字幕常为 JSON 格式：[{"text": "...", "start": ...}, ...]
        B站字幕为 JSON：{"body": [{"content": "...", "from": ...}, ...]}
        通用 SRT：1\\n00:00:01,000 --> 00:00:03,000\\n文本\\n
        """
        try:
            r = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
            content = r.text.strip()
            if not content:
                return ""
            # JSON 数组格式（抖音常见）
            if content.startswith("[") or content.startswith("{"):
                try:
                    import json as _json
                    data = _json.loads(content)
                    parts = []
                    if isinstance(data, list):
                        for item in data:
                            t = item.get("text") or item.get("content") or ""
                            if t:
                                parts.append(t)
                    elif isinstance(data, dict):
                        body = data.get("body", data)
                        if isinstance(body, list):
                            for item in body:
                                t = item.get("text") or item.get("content") or ""
                                if t:
                                    parts.append(t)
                    text = "".join(parts).strip()
                    if text:
                        return text
                except Exception:
                    pass
            # SRT/VTT 格式
            lines = content.split("\n")
            texts = []
            for line in lines:
                line = line.strip()
                # 跳过序号、时间轴、空行
                if not line or line.isdigit() or "-->" in line or line.startswith("WEBVTT"):
                    continue
                texts.append(line)
            return " ".join(texts).strip()
        except Exception as e:
            self.logger.debug(f"字幕下载失败: {e}")
            return ""

    def _ytdlp_download_audio(self, url: str, output_template: str) -> Optional[Path]:
        """用 yt-dlp 下载音频，返回下载的文件路径

        cookies 自动获取（用户无感知），多浏览器自动回退：
        - 优先 cookies_from_browser 配置的浏览器，失败自动尝试其他浏览器
        - Chrome 运行时会锁定 cookies 数据库（yt-dlp #7271），自动回退到 edge/firefox
        - 其次 cookies_file：手动指定的 Netscape 格式文件
        """
        cookies_path = Path(self.cookies_file) if self.cookies_file else None
        use_cookies_file = bool(cookies_path and cookies_path.exists() and cookies_path.is_file())
        configured_browser = self.cookies_from_browser.lower().strip() if self.cookies_from_browser else ""
        # 多浏览器回退列表：配置的优先，再尝试其他常见浏览器
        all_browsers = ["edge", "chrome", "firefox", "brave"]  # edge优先（chrome运行时锁定cookies数据库）
        if configured_browser and configured_browser in all_browsers:
            all_browsers = [configured_browser] + [b for b in all_browsers if b != configured_browser]
        elif configured_browser:
            all_browsers = [configured_browser] + all_browsers
        if not configured_browser and not use_cookies_file:
            all_browsers = []  # 未配置则不尝试浏览器

        work_dir = Path(output_template).parent
        base_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.douyin.com/",
            },
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        }

        # 方式 1：Python API，多浏览器回退
        try:
            import yt_dlp
            last_err = ""
            # 尝试配置的浏览器（多浏览器回退），再尝试 cookies 文件
            attempts = []
            for b in all_browsers:
                attempts.append(("browser", b))
            if use_cookies_file:
                attempts.append(("file", str(cookies_path)))
            attempts.append(("none", None))  # 最后无 cookies 尝试一次

            for cookie_type, cookie_val in attempts:
                opts = dict(base_opts)
                if cookie_type == "browser":
                    opts["cookiesfrombrowser"] = (cookie_val,)
                    self.logger.info(f"yt-dlp 尝试从 {cookie_val} 读取 cookies")
                elif cookie_type == "file":
                    opts["cookiefile"] = cookie_val
                    self.logger.info(f"yt-dlp 使用 cookies 文件: {cookie_val}")
                else:
                    self.logger.info("yt-dlp 无 cookies 尝试（最后手段）")
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                    for ext in ("mp3", "m4a", "webm", "opus", "wav"):
                        files = list(work_dir.glob(f"ref.*{ext}"))
                        if files:
                            return files[0]
                    return None  # 下载成功但找不到文件
                except Exception as e:
                    last_err = str(e)
                    err_lower = last_err.lower()
                    # cookies 读取失败（数据库锁定）→ 换浏览器继续
                    if "could not copy" in err_lower and "cookie" in err_lower:
                        self.logger.warning(f"{cookie_val} cookies 数据库锁定（浏览器运行中），尝试其他浏览器")
                        continue
                    # Fresh cookies needed → cookies 无效，换来源继续
                    if "fresh cookies" in err_lower:
                        self.logger.warning(f"{cookie_val} cookies 无效或未登录抖音，尝试其他来源")
                        continue
                    # 其他错误（非 cookies 问题）→ 不再重试
                    self.logger.warning(f"yt-dlp 下载失败: {last_err[:120]}")
                    break
            if last_err:
                self.logger.warning(f"yt-dlp 所有 cookies 来源均失败，最后错误: {last_err[:120]}")
        except ImportError:
            self.logger.warning("yt-dlp Python 模块未安装")
        except Exception as e:
            self.logger.warning(f"yt-dlp Python API 异常: {e}")

        # 方式 2：命令行（最后兜底，用配置的浏览器）
        if shutil.which("yt-dlp"):
            import subprocess
            cmd = [
                "yt-dlp", "-x", "--audio-format", "mp3",
                "-o", output_template,
                "--no-playlist", "--no-warnings", url,
            ]
            if configured_browser:
                cmd.extend(["--cookies-from-browser", configured_browser])
            elif use_cookies_file:
                cmd.extend(["--cookies", str(cookies_path)])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                work_dir = Path(output_template).parent
                files = list(work_dir.glob("ref.*"))
                if files:
                    return files[0]
            self.logger.warning(f"yt-dlp 命令行失败: {result.stderr[-200:]}")
        return None

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

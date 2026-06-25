"""文案原创度与风控检测模块

在 script_write 之后、tts 之前插入，对生成文案做三重检测：
1. SimHash 查重：与历史文案库比对，避免重复发布近似内容
2. 违禁词扫描：广告法极限词 / 平台敏感词 / 医疗金融风险词
3. LLM 语义风控：调 LLM 做语义级风险判断（可选）

任一检测不通过即返回失败，触发 orchestrator 指数退避重试 script_write，
形成"生成 → 检测 → 不合规则重写"的闭环。

降级策略：
- jieba 未装：SimHash 退化为字符 bigram（精度略降，仍可用）
- 历史库不存在：跳过查重，仅做违禁词 + LLM 检测
- LLM mock 模式：跳过 LLM 风控（避免用 mock 文案误判）
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.llm_client import LLMClient, get_llm_client
from ..core.text_similarity import (
    hamming_distance,
    is_likely_duplicate,
    normalize_text,
    simhash,
    simhash_similarity,
)


# 违禁词扫描用正则特殊字符转义
import re


class OriginalityChecker(BaseModule):
    """文案原创度与风控检测模块"""

    name = "originality_check"
    requires_gpu = False

    def __init__(self, config=None, llm_client: LLMClient | None = None):
        super().__init__(config)
        ocfg = self.config.get("originality", {}) or {}
        self.enabled = ocfg.get("enabled", True)
        self.simhash_threshold = float(ocfg.get("simhash_threshold", 0.85))
        self.banned_words_file = Path(
            ocfg.get("banned_words_file", "./config/banned_words.txt")
        )
        self.history_db = Path(
            ocfg.get("history_db", "./workspace_data/originality_history.db")
        )
        self.llm_risk_check = bool(ocfg.get("llm_risk_check", True))
        self.auto_fix_banned = bool(ocfg.get("auto_fix_banned", True))
        self.banned_words_max_report = int(ocfg.get("banned_words_max_report", 10))
        self.llm = llm_client or get_llm_client()
        self._banned_words: list[str] | None = None  # 延迟加载

    def setup(self) -> None:
        # 加载违禁词库（不存在不报错，仅记录）
        self._banned_words = self._load_banned_words()
        self.logger.info(
            f"文案风控模块初始化 enabled={self.enabled} "
            f"banned_words={len(self._banned_words)} "
            f"simhash_threshold={self.simhash_threshold} "
            f"llm_risk={self.llm_risk_check} llm_mock={self.llm.is_mock}"
        )
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """执行查重 + 风控检测"""
        # 未启用直接跳过
        if not self.enabled:
            return ModuleResult(
                success=True,
                data={"skipped": True, "reason": "originality disabled"},
            )

        # mock LLM 模式跳过查重：mock 文案是固定模板，多次运行必然相似，
        # 查重无意义且会误伤流程测试。LLM 风控同理跳过。
        # 仍执行违禁词扫描（这是确定性的本地检测，与 LLM 无关）。
        if self.llm.is_mock:
            self.logger.info("LLM mock 模式：跳过 SimHash 查重与 LLM 风控，仅做违禁词扫描")
            text = ctx.script_text or ctx.input_script
            if not text:
                return ModuleResult(success=False, error="无文案可检测")
            banned_hits = self._scan_banned_words(text)
            if banned_hits:
                preview = "、".join(banned_hits[:self.banned_words_max_report])
                return ModuleResult(
                    success=False,
                    error=f"文案命中违禁词：{preview}",
                    data={"banned_words": banned_hits},
                )
            ctx.metadata["originality"] = {
                "status": "passed_mock",
                "char_count": len(text),
                "note": "mock 模式仅违禁词扫描",
            }
            return ModuleResult(
                success=True,
                data={"skipped_dupcheck": True, "reason": "llm mock mode"},
            )

        text = ctx.script_text or ctx.input_script
        if not text:
            return ModuleResult(
                success=False, error="无文案可检测",
            )

        try:
            start = time.time()
            normalized = normalize_text(text)
            fingerprint = simhash(text)
            report: dict[str, Any] = {
                "char_count": len(text),
                "simhash": fingerprint,
            }

            # === 1. SimHash 查重（与历史库比对）===
            dup_hit = self._check_duplicate(fingerprint)
            if dup_hit:
                report["duplicate"] = dup_hit
                return ModuleResult(
                    success=False,
                    error=(
                        f"文案与历史相似度过高（{dup_hit['similarity']:.1%}，"
                        f"job={dup_hit['job_id']}），建议重新仿写"
                    ),
                    data=report,
                )

            # === 2. 违禁词扫描 ===
            banned_hits = self._scan_banned_words(text)
            if banned_hits:
                # 自动修正：调 LLM 去掉违禁词（避免流程卡死在重试）
                if self.auto_fix_banned and not self.llm.is_mock:
                    fixed = self._auto_fix_banned_words(text, banned_hits)
                    if fixed and fixed != text:
                        # 修正后重新扫描
                        new_hits = self._scan_banned_words(fixed)
                        if not new_hits:
                            self.logger.info(
                                f"违禁词自动修正成功: {banned_hits} -> 已替换，"
                                f"文案 {len(text)}字 -> {len(fixed)}字"
                            )
                            text = fixed
                            ctx.script_text = text
                            normalized = normalize_text(text)
                            fingerprint = simhash(text)
                            report["banned_auto_fixed"] = banned_hits
                            report["char_count"] = len(text)
                            report["simhash"] = fingerprint
                            # 跳过下面的失败返回，继续走 LLM 风控
                            banned_hits = []
                            report.pop("banned_words", None)
                        else:
                            self.logger.warning(
                                f"违禁词自动修正后仍命中: {new_hits}"
                            )
                if banned_hits:
                    report["banned_words"] = banned_hits
                    preview = "、".join(banned_hits[:self.banned_words_max_report])
                    return ModuleResult(
                        success=False,
                        error=f"文案命中违禁词：{preview}",
                        data=report,
                    )

            # === 3. LLM 语义风控（可选）===
            if self.llm_risk_check and not self.llm.is_mock:
                risk = self._llm_risk_check(text)
                report["llm_risk"] = risk
                if risk.get("level") == "high":
                    return ModuleResult(
                        success=False,
                        error=f"LLM 风控拦截：{risk.get('reason', '高风险')}",
                        data=report,
                    )

            # === 全部通过：写入历史库 ===
            self._save_to_history(ctx.job_id, text, fingerprint)
            report["status"] = "passed"
            report["elapsed"] = round(time.time() - start, 3)
            ctx.metadata["originality"] = report

            self.logger.info(
                f"文案风控通过 simhash={hex(fingerprint)} "
                f"banned=0 llm={'skip' if self.llm.is_mock else 'ok'}"
            )
            return ModuleResult(success=True, data=report)

        except Exception as e:
            # 风控异常不应阻断流程：降级为放行 + 记录
            self.logger.warning(f"文案风控异常，降级放行：{e}")
            ctx.metadata["originality"] = {"status": "error", "error": str(e)}
            return ModuleResult(
                success=True,
                data={"degraded": True, "error": str(e)},
            )

    # ============ 查重 ============

    def _check_duplicate(self, fingerprint: int) -> Optional[dict]:
        """与历史库比对，返回最近一个重复项（None 表示未重复）"""
        if not self.history_db.exists():
            return None
        try:
            conn = sqlite3.connect(str(self.history_db))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT job_id, simhash, created_at, preview FROM history "
                "ORDER BY created_at DESC LIMIT 2000"
            ).fetchall()
            conn.close()
        except Exception as e:
            self.logger.warning(f"读取历史库失败：{e}")
            return None

        best: Optional[dict] = None
        for row in rows:
            # simhash 存为 TEXT 字符串，读取时转回 int
            try:
                other = int(row["simhash"])
            except (ValueError, TypeError):
                continue
            sim = simhash_similarity(fingerprint, other)
            if sim >= self.simhash_threshold:
                if best is None or sim > best["similarity"]:
                    best = {
                        "job_id": row["job_id"],
                        "similarity": round(sim, 4),
                        "hamming": hamming_distance(fingerprint, other),
                        "preview": row["preview"],
                    }
        return best

    def _save_to_history(
        self, job_id: str, text: str, fingerprint: int
    ) -> None:
        """写入历史库（供后续查重）"""
        try:
            self.history_db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.history_db))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    job_id TEXT,
                    simhash INTEGER,
                    normalized_hash INTEGER,
                    preview TEXT,
                    char_count INTEGER,
                    created_at REAL,
                    PRIMARY KEY (job_id)
                )
            """)
            conn.execute(
                "INSERT OR REPLACE INTO history "
                "(job_id, simhash, normalized_hash, preview, char_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                # simhash 是无符号64位，可能超出 SQLite 有符号 INTEGER 范围，存为 TEXT
                (job_id, str(fingerprint), str(fingerprint),
                 text[:80], len(text), time.time()),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.warning(f"写入历史库失败：{e}")

    # ============ 违禁词扫描 ============

    def _load_banned_words(self) -> list[str]:
        """加载违禁词库"""
        if not self.banned_words_file.exists():
            self.logger.debug(f"违禁词库不存在：{self.banned_words_file}")
            return []
        words: list[str] = []
        try:
            for line in self.banned_words_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # 去掉分类标记行（如 [广告法极限词]）
                if line.startswith("[") and line.endswith("]"):
                    continue
                words.append(line)
        except Exception as e:
            self.logger.warning(f"违禁词库加载失败：{e}")
        return words

    def _scan_banned_words(self, text: str) -> list[str]:
        """扫描文案中的违禁词，返回命中列表（去重保序）"""
        if not self._banned_words:
            return []
        hits: list[str] = []
        seen = set()
        for word in self._banned_words:
            if word in text and word not in seen:
                hits.append(word)
                seen.add(word)
        return hits

    def _auto_fix_banned_words(self, text: str, banned: list[str]) -> Optional[str]:
        """调 LLM 自动修正文案，去除违禁词（保持语义和口播风格）

        Returns:
            修正后的文案（str），失败返回 None
        """
        prompt = (
            "以下是短视频口播文案，其中包含一些平台违禁/极限词。"
            "请替换这些词为合规的近义表达，保持文案的口播风格、语气和长度基本不变，"
            "直接输出修改后的完整文案，不要解释。\n\n"
            f"违禁词列表：{'、'.join(banned)}\n\n"
            f"原始文案：\n{text}"
        )
        try:
            resp = self.llm.chat([
                {"role": "system", "content": "你是短视频文案合规审核专家。"},
                {"role": "user", "content": prompt},
            ])
            # 后处理：去多余空行
            lines = [ln.strip() for ln in resp.splitlines() if ln.strip()]
            fixed = "\n".join(lines)
            return fixed if fixed else None
        except Exception as e:
            self.logger.warning(f"违禁词自动修正 LLM 调用失败：{e}")
            return None

    # ============ LLM 语义风控 ============

    def _llm_risk_check(self, text: str) -> dict:
        """调 LLM 做语义级风险检测

        返回: {"level": "low"|"medium"|"high", "reason": str, "risks": list}
        """
        prompt = (
            "请对以下短视频口播文案做平台风控检测，判断在抖音/小红书/B站/视频号发布的风险。\n"
            "检测维度：1) 违禁词/极限词 2) 虚假宣传 3) 医疗/金融违规 4) 引流违规 5) 其他敏感。\n\n"
            "请严格按以下 JSON 格式返回（不要其他内容）：\n"
            '{"level": "low|medium|high", "reason": "一句话说明", "risks": ["具体风险点"]}\n\n'
            f"文案：\n{text}"
        )
        try:
            resp = self.llm.chat([
                {"role": "system", "content": "你是短视频平台风控审核专家。"},
                {"role": "user", "content": prompt},
            ])
            return self._parse_llm_risk(resp)
        except Exception as e:
            self.logger.warning(f"LLM 风控调用失败，降级为 low：{e}")
            return {"level": "low", "reason": "LLM 调用失败，已降级", "risks": []}

    @staticmethod
    def _parse_llm_risk(resp: str) -> dict:
        """解析 LLM 返回的风险 JSON（容错）"""
        # 尝试提取 JSON 块
        try:
            # 直接解析
            return json.loads(resp.strip())
        except json.JSONDecodeError:
            pass
        # 尝试提取 {...} 片段
        m = re.search(r"\{[^{}]*\}", resp, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {"level": "low", "reason": "LLM 返回解析失败，已降级", "risks": []}

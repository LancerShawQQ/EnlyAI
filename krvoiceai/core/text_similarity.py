"""文本相似度工具（SimHash + 海明距离）

用于文案查重：把文案压缩为 64 位指纹，通过海明距离快速判断相似度。
SimHash 特性：
  - 局部敏感：相似文本的指纹只有少数位不同
  - 海明距离 ≤ 3 通常视为近似重复
  - 可选 jieba 分词提升中文精度；未装 jieba 时退化为字符 n-gram
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


def _tokenize(text: str) -> list[str]:
    """中文分词：优先 jieba，失败则用字符 bigram 兜底"""
    try:
        import jieba
        return [t for t in jieba.lcut(text) if t.strip()]
    except ImportError:
        # 兜底：字符级 bigram
        chars = [c for c in text if c.strip()]
        if len(chars) < 2:
            return chars
        return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


def _hash64(token: str) -> int:
    """稳定的 64 位哈希（FNV-1a 变体，纯 Python 实现）"""
    h = 14695981039346656037  # FNV offset basis (64-bit)
    for byte in token.encode("utf-8"):
        h ^= byte
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF  # FNV prime, 保持 64 位
    return h


def simhash(text: str, hash_bits: int = 64) -> int:
    """计算文本的 SimHash 指纹

    Args:
        text: 输入文本
        hash_bits: 指纹位数（默认 64）

    Returns:
        int 指纹（hash_bits 位）
    """
    tokens = _tokenize(text)
    if not tokens:
        return 0

    # 统计词频作为权重
    weights = Counter(tokens)

    # 加权累加每位
    vec = [0] * hash_bits
    for token, weight in weights.items():
        h = _hash64(token)
        for i in range(hash_bits):
            bit = (h >> i) & 1
            vec[i] += weight if bit else -weight

    # 符号位化
    fingerprint = 0
    for i in range(hash_bits):
        if vec[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """计算两个指纹的海明距离（不同位数）"""
    return bin((a ^ b) & 0xFFFFFFFFFFFFFFFF).count("1")


def simhash_similarity(a: int, b: int, hash_bits: int = 64) -> float:
    """两个 SimHash 指纹的相似度（0~1，1 表示完全相同）"""
    if hash_bits == 0:
        return 0.0
    dist = hamming_distance(a, b)
    return 1.0 - dist / hash_bits


def is_likely_duplicate(
    a: int, b: int, threshold: float = 0.85, hash_bits: int = 64
) -> bool:
    """判断两个指纹是否近似重复

    Args:
        threshold: 相似度阈值（≥ 视为重复）。0.85 对应海明距离约 9 位
    """
    return simhash_similarity(a, b, hash_bits) >= threshold


def normalize_text(text: str) -> str:
    """文本归一化：去除空白/标点/大小写差异，提升查重稳定性"""
    # 去除所有空白
    text = re.sub(r"\s+", "", text)
    # 去除常见标点（中英文）
    text = re.sub(r"[，。！？、；：“”‘’（）【】《》,.!?;:\"'()\[\]<>]", "", text)
    return text.lower()

"""配置管理系统

支持 YAML 配置文件 + 环境变量覆盖，提供类型安全的访问。
"""
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.yaml"
USER_CONFIG_PATH = PROJECT_ROOT / "config" / "user_config.yaml"


class Config:
    """配置访问器，支持点号路径访问。"""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def load(
        cls,
        config_path: str | Path | None = None,
        env_file: str | Path | None = None,
    ) -> "Config":
        """加载配置。

        优先级：环境变量 > 用户配置文件 > 默认配置文件

        Args:
            config_path: 显式指定的用户配置文件路径。若为 None，则自动加载
                         config/user_config.yaml（若存在）。
        """
        if env_file:
            load_dotenv(env_file)
        else:
            # 自动加载项目根目录 .env（若存在）
            auto_env = PROJECT_ROOT / ".env"
            if auto_env.exists():
                load_dotenv(auto_env)

        # 加载默认配置
        with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 确定用户配置文件路径：优先使用显式传入的，否则自动加载 user_config.yaml
        user_paths: list[Path] = []
        if config_path:
            user_paths.append(Path(config_path))
        else:
            # 自动加载 user_config.yaml（由 SettingsManager 维护）
            if USER_CONFIG_PATH.exists():
                user_paths.append(USER_CONFIG_PATH)

        # 合并用户配置（按顺序合并，后者覆盖前者）
        for path in user_paths:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    user_data = yaml.safe_load(f) or {}
                data = _deep_merge(data, user_data)

        # 环境变量覆盖
        data = _apply_env_overrides(data)

        return cls(data)

    def get(self, path: str, default: Any = None) -> Any:
        """点号路径访问，例如 config.get('llm.api_key')"""
        keys = path.split(".")
        cur: Any = self._data
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur

    def set(self, path: str, value: Any) -> None:
        """设置配置项（运行时修改，不持久化）"""
        keys = path.split(".")
        cur = self._data
        for k in keys[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[keys[-1]] = value

    def ensure_dirs(self) -> None:
        """确保所有配置中提到的目录存在"""
        dir_paths = [
            self.get("project.work_root"),
            self.get("project.temp_root"),
            self.get("tts.voices_dir"),
            self.get("avatar.avatars_dir"),
            self.get("asr.model_cache"),
            self.get("composer.bgm_dir"),
            self.get("cover.templates_dir"),
            self.get("publisher.cookies_dir"),
        ]
        for p in dir_paths:
            if p:
                Path(p).mkdir(parents=True, exist_ok=True)
        # 日志目录
        log_file = self.get("logging.file")
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self._data)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并字典，override 覆盖 base"""
    result = deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = deepcopy(v)
    return result


def _apply_env_overrides(data: dict) -> dict:
    """应用环境变量覆盖

    环境变量格式：KRVOICEAI_<大写点号路径，下划线分隔>
    例如 llm.api_key -> KRVOICEAI_LLM_API_KEY
    """
    prefix = "KRVOICEAI_"

    def walk(node: dict, path_parts: list[str]) -> dict:
        result = {}
        for k, v in node.items():
            cur_path = path_parts + [k]
            env_key = prefix + "_".join(cur_path).upper()
            if isinstance(v, dict):
                result[k] = walk(v, cur_path)
                # 检查是否有直接对应的环境变量
                if env_key in os.environ:
                    # 环境变量直接覆盖整个字典节点（少见，跳过）
                    pass
            else:
                if env_key in os.environ:
                    result[k] = _cast_env(os.environ[env_key], v)
                else:
                    result[k] = v
        return result

    return walk(data, [])


def _cast_env(env_val: str, original: Any) -> Any:
    """根据原始值类型转换环境变量字符串"""
    if isinstance(original, bool):
        return env_val.lower() in ("1", "true", "yes", "on")
    if isinstance(original, int):
        try:
            return int(env_val)
        except ValueError:
            return original
    if isinstance(original, float):
        try:
            return float(env_val)
        except ValueError:
            return original
    if isinstance(original, list):
        # 逗号分隔
        return [x.strip() for x in env_val.split(",")]
    return env_val


# 全局单例
_config: Config | None = None


def get_config(reload: bool = False) -> Config:
    """获取全局配置单例"""
    global _config
    if _config is None or reload:
        _config = Config.load()
        _config.ensure_dirs()
    return _config

"""Configuration models using Pydantic Settings. Loads from config.yaml + .env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ModelProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 120


class ModelConfig(BaseModel):
    """Top-level model configuration."""

    default_provider: str = "openai"
    providers: dict[str, ModelProviderConfig] = Field(default_factory=lambda: {
        "openai": ModelProviderConfig(provider="openai", model="gpt-4o"),
    })


class TerminalConfig(BaseModel):
    """Terminal / CLI display settings."""

    theme: str = "dark"
    code_theme: str = "monokai"
    max_output_lines: int = 500
    show_timestamps: bool = True
    syntax_highlighting: bool = True
    pager: str = "auto"


class MemoryConfig(BaseModel):
    """Memory store settings."""

    enabled: bool = True
    db_path: str = "~/.nexusagent/memory.db"
    max_entries: int = 10000
    categories: list[str] = Field(default_factory=lambda: [
        "conversation", "fact", "task", "preference", "context",
    ])
    auto_save: bool = True


class GatewayConfig(BaseModel):
    """Gateway / multi-platform settings."""

    enabled: bool = False
    allowlist: list[str] = Field(default_factory=list)
    require_auth: bool = False
    max_message_length: int = 4096
    session_timeout_minutes: int = 60
    telegram_token: str = ""
    discord_token: str = ""


class ToolConfig(BaseModel):
    """Tool settings."""

    web_search_enabled: bool = True
    web_fetch_enabled: bool = True
    code_execute_enabled: bool = True
    file_read_enabled: bool = True
    file_write_enabled: bool = True
    code_sandbox: str = "docker"
    max_file_size_mb: int = 10
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)


class SecurityConfig(BaseModel):
    """Security settings."""

    api_key_encryption: bool = True
    require_approval_for_tools: bool = False
    audit_log: bool = True
    audit_log_path: str = "~/.nexusagent/audit.log"
    max_rate_limit: int = 60  # requests per minute
    ip_allowlist: list[str] = Field(default_factory=list)


class NexusConfig(BaseModel):
    """Root configuration model aggregating all sub-configs."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    terminal: TerminalConfig = Field(default_factory=TerminalConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    data_dir: str = "~/.nexusagent"
    log_level: str = "INFO"


def load_config(config_path: str | Path | None = None, env_path: str | Path | None = None) -> NexusConfig:
    """
    Load configuration from a YAML file and optional .env file.

    Environment variables override YAML values. Provider API keys are
    read from environment variables like OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.

    Args:
        config_path: Path to config.yaml. Defaults to ./config/default_config.yaml.
        env_path: Path to .env file.

    Returns:
        A fully resolved NexusConfig instance.
    """
    import yaml

    if config_path is None:
        config_path = Path(__file__).parent / "default_config.yaml"
    config_path = Path(config_path)

    raw: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

    # Load .env if provided
    if env_path:
        _load_dotenv(Path(env_path))

    # Override with environment variables
    env_overrides: dict[str, Any] = {}
    env_map = {
        "NEXUS_DATA_DIR": "data_dir",
        "NEXUS_LOG_LEVEL": "log_level",
        "NEXUS_DEFAULT_PROVIDER": ("model", "default_provider"),
        "NEXUS_GATEWAY_TELEGRAM_TOKEN": ("gateway", "telegram_token"),
        "NEXUS_GATEWAY_DISCORD_TOKEN": ("gateway", "discord_token"),
    }
    for env_var, key in env_map.items():
        val = os.environ.get(env_var)
        if val is not None:
            if isinstance(key, tuple):
                env_overrides.setdefault(key[0], {})[key[1]] = val
            else:
                env_overrides[key] = val

    # Merge env overrides into raw config
    _deep_merge(raw, env_overrides)

    # Inject API keys from environment into provider configs
    providers = raw.get("model", {}).get("providers", {})
    for name, prov in providers.items():
        env_key = f"{name.upper()}_API_KEY"
        if env_key in os.environ and not prov.get("api_key"):
            prov["api_key"] = os.environ[env_key]

    return NexusConfig(**raw)


def _load_dotenv(path: Path) -> None:
    """Simple .env loader — sets os.environ for missing keys."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Recursively merge override into base (mutates base)."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v

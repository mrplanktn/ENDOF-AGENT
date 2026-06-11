# Configuration Reference

## Overview

NexusAgent uses a layered configuration system:

1. **Default values** (hardcoded in Pydantic models)
2. **config/default_config.yaml** (project defaults)
3. **User config file** (overrides defaults)
4. **Environment variables** (highest priority)
5. **CLI flags** (override everything)

## Config File Location

Default: `config/default_config.yaml`
Custom: Use `--config /path/to/config.yaml` flag

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | `sk-proj-...` |
| `ANTHROPIC_API_KEY` | Anthropic API key | `sk-ant-...` |
| `GOOGLE_API_KEY` | Google AI API key | `AIza...` |
| `GROQ_API_KEY` | Groq API key | `gsk_...` |
| `MISTRAL_API_KEY` | Mistral API key | `...` |
| `TELEGRAM_TOKEN` | Telegram bot token | `123456:ABC...` |
| `DISCORD_TOKEN` | Discord bot token | `MTIz...` |
| `SLACK_BOT_TOKEN` | Slack bot token | `xoxb-...` |
| `NEXUS_DATA_DIR` | Data directory path | `~/.nexusagent` |
| `NEXUS_LOG_LEVEL` | Logging level | `INFO` |
| `NEXUS_DEFAULT_PROVIDER` | Default LLM provider | `openai` |
| `NEXUS_ENCRYPTION_KEY` | Credential encryption key | `my-secret-key` |

## Sections

### `model`

```yaml
model:
  default_provider: "openai"
  providers:
    openai:
      provider: "openai"
      model: "gpt-4o"
      api_key: ""  # Prefer OPENAI_API_KEY env var
      base_url: ""  # Override for compatible APIs
      max_tokens: 4096
      temperature: 0.7
      timeout: 120
```

### `terminal`

```yaml
terminal:
  theme: "dark"           # dark, light
  code_theme: "monokai"   # Pygments syntax theme
  max_output_lines: 500
  show_timestamps: true
  syntax_highlighting: true
  pager: "auto"           # auto, always, never
```

### `memory`

```yaml
memory:
  enabled: true
  db_path: "~/.nexusagent/memory.db"
  max_entries: 10000
  categories:
    - conversation
    - fact
    - task
    - preference
    - context
  auto_save: true
```

### `gateway`

```yaml
gateway:
  enabled: false
  allowlist: []             # User IDs allowed (empty = all)
  require_auth: false
  max_message_length: 4096
  session_timeout_minutes: 60
  telegram_token: ""
  discord_token: ""
```

### `tools`

```yaml
tools:
  web_search_enabled: true
  web_fetch_enabled: true
  code_execute_enabled: true
  file_read_enabled: true
  file_write_enabled: true
  code_sandbox: "docker"   # docker, local, none
  max_file_size_mb: 10
  allowed_domains: []      # Empty = all allowed
  blocked_domains:
    - "localhost"
```

### `security`

```yaml
security:
  api_key_encryption: true
  require_approval_for_tools: false
  audit_log: true
  audit_log_path: "~/.nexusagent/audit.log"
  max_rate_limit: 60
  ip_allowlist: []
```

## Pydantic Models

All configuration is validated through Pydantic models in `config/settings.py`:

- `NexusConfig` — Root model
- `ModelConfig` / `ModelProviderConfig` — LLM settings
- `TerminalConfig` — CLI display
- `MemoryConfig` — Memory store
- `GatewayConfig` — Multi-platform gateway
- `ToolConfig` — Tool availability and limits
- `SecurityConfig` — Security policies

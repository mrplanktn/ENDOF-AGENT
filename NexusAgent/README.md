<div align="center">

# 🌐 NexusAgent

**The Universal AI Agent Framework**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/nexusagent/nexusagent/ci.yml?branch=main)](https://github.com/nexusagent/nexusagent/actions)
[![codecov](https://img.shields.io/codecov/c/github/nexusagent/nexusagent)](https://codecov.io/gh/nexusagent/nexusagent)
[![Discord](https://img.shields.io/discord/000000000000000000?color=7289da&label=Discord&logo=discord&logoColor=white)](https://discord.gg/nexusagent)
[![PyPI](https://img.shields.io/pypi/v/nexusagent?color=blueviolet)](https://pypi.org/project/nexusagent/)
[![Downloads](https://img.shields.io/pypi/dm/nexusagent?color=ff69b4)](https://pypi.org/project/nexusagent/)

*One agent. Every platform. Every model. Every tool.*

[Features](#-features) · [Quick Start](#-quick-start) · [Architecture](#-architecture) · [Docs](#-documentation) · [Contributing](CONTRIBUTING.md)

</div>

---

## 🚀 Features

- 🤖 **Multi-LLM Support** — OpenAI, Anthropic, Google, Groq, Mistral, Ollama, and more
- 💬 **Interactive Terminal Chat** — Rich CLI with syntax highlighting, history, and tab completion
- 🌐 **Multi-Platform Gateway** — Deploy on Telegram, Discord, Slack, WhatsApp simultaneously
- 🧠 **Persistent Memory** — SQLite + FTS5 full-text search across all conversations
- 🛠️ **20+ Built-in Tools** — Web search, code execution, file I/O, browser automation
- 📁 **Skills System** — Modular SKILL.md files for extensible agent capabilities
- 💾 **Session Management** — Create, resume, search, and manage conversation sessions
- 🔐 **Authentication & Security** — API key management, OAuth tokens, credential pooling
- 📊 **Audit Logging** — Full trail of tool calls, messages, and decisions
- ⚙️ **YAML + ENV Config** — Flexible configuration with environment variable overrides
- 🐳 **Docker Sandboxed Execution** — Run code safely in isolated containers
- 🎨 **Rich Output** — Beautiful tables, panels, markdown rendering in terminal
- 🔍 **Full-Text Search** — Search across memories, sessions, and messages
- 🧩 **Plugin Architecture** — Extend with custom tools, adapters, and providers
- 📱 **Voice & Media Support** — Handle images, documents, audio across platforms
- 🔄 **Credential Pooling** — Round-robin across multiple API keys for rate limits
- 🏗️ **Pydantic Config Validation** — Type-safe configuration with sensible defaults
- 📖 **Comprehensive Docs** — Architecture, configuration, tools, and provider guides
- 🧪 **Well-Tested** — Unit and integration test suites included
- ⚡ **Async First** — Built on asyncio for high-performance concurrent operations
- 🪶 **Lightweight** — Minimal dependencies, fast startup
- 📦 **pip Installable** — Simple `pip install nexusagent` to get started

## ⚡ Quick Start

### Install

```bash
pip install nexusagent
```

Or with the installer script:

```bash
curl -sSL https://raw.githubusercontent.com/nexusagent/nexusagent/main/scripts/install.sh | bash
```

### Configure

```bash
# Copy example env and add your API key
cp config/.env.example .env
echo "OPENAI_API_KEY=sk-..." >> .env
```

### Chat

```bash
nexus chat
```

### Run the Gateway (Telegram + Discord)

```bash
nexus gateway start
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        NexusAgent Core                          │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │  Gateway  │  │  Memory  │  │  Skills  │  │   Sessions   │   │
│  │  Layer    │  │  Store   │  │  Manager │  │    Store      │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
│       │              │              │               │           │
│  ┌────┴──────────────┴──────────────┴───────────────┴────────┐  │
│  │                    Agent Core                             │  │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐  │  │
│  │  │ Router  │  │  Tools   │  │ Provider │  │  Context   │  │  │
│  │  │         │  │  Engine  │  │ Manager  │  │  Builder   │  │  │
│  │  └─────────┘  └──────────┘  └──────────┘  └───────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐    │
│  │   Config    │  │     Auth     │  │      CLI / REPL     │    │
│  │   (YAML)    │  │   Manager    │  │   (Rich + Prompt)   │    │
│  └─────────────┘  └──────────────┘  └─────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
         │                  │                    │
    ┌────┴────┐       ┌────┴────┐          ┌────┴────┐
    │Telegram │       │ Discord │          │  Slack  │
    │Adapter  │       │ Adapter │          │ Adapter │
    └─────────┘       └─────────┘          └─────────┘
```

## 🌍 Supported Platforms

| Platform | Status | Features |
|----------|--------|----------|
| 📱 Telegram | ✅ Stable | Text, photos, docs, voice, slash commands |
| 🎮 Discord | ✅ Stable | Channels, DMs, attachments, slash commands |
| 💬 Slack | 🔜 Planned | Channels, threads, file uploads |
| 📲 WhatsApp | 🔜 Planned | Business API integration |

## 🤖 Supported Providers

- **OpenAI** — GPT-4o, GPT-4, GPT-3.5-turbo, o1, o3
- **Anthropic** — Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku
- **Google** — Gemini 1.5 Pro, Gemini 1.5 Flash
- **Groq** — Llama 3, Mixtral
- **Mistral** — Mistral Large, Medium, Small
- **Ollama** — Any local model (Llama, Qwen, Phi, etc.)
- **Custom** — Any OpenAI-compatible API endpoint

## 🛠️ Built-in Tools

- `web_search` — Search the web via API
- `web_fetch` — Fetch and extract web page content
- `code_execute` — Execute code in Docker sandbox
- `file_read` / `file_write` — Read and write local files
- `memory` — Search and save to persistent memory
- `browser` — Playwright browser automation
- `skills` — Skill lookup and injection

## 📖 CLI Reference

```bash
nexus chat                    # Start interactive chat
nexus setup                   # Run setup wizard
nexus config show             # Show current configuration
nexus config validate         # Validate configuration
nexus model list              # List available models
nexus model set gpt-4o        # Switch active model
nexus tools                   # List available tools
nexus skills list             # List loaded skills
nexus skills search <query>   # Search skills
nexus skills create -n <name> # Create a new skill
nexus sessions list           # List sessions
nexus sessions resume <id>    # Resume a session
nexus sessions delete <id>    # Delete a session
nexus gateway start           # Start the platform gateway
nexus gateway stop            # Stop the gateway
nexus gateway status          # Check gateway status
```

## ⚙️ Configuration

See [docs/configuration.md](docs/configuration.md) for the full reference.

```yaml
model:
  default_provider: openai
  providers:
    openai:
      model: gpt-4o
      temperature: 0.7
      max_tokens: 4096

memory:
  enabled: true
  auto_save: true

gateway:
  enabled: true
  telegram_token: ${TELEGRAM_TOKEN}
  discord_token: ${DISCORD_TOKEN}
```

## 📚 Documentation

- [Architecture](docs/architecture.md) — System design and data flow
- [Configuration](docs/configuration.md) — Complete config reference
- [Tools](docs/tools.md) — Tool development guide
- [Providers](docs/providers.md) — LLM provider setup

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/nexusagent/nexusagent
cd nexusagent
pip install -e ".[dev]"
pytest
```

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with ❤️ by the NexusAgent Team**

</div>

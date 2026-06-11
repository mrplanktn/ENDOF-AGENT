# NexusAgent Architecture

## Overview

NexusAgent is a modular AI agent framework designed for extensibility across
platforms, providers, and tools. The architecture separates concerns into
independently testable layers.

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          NexusAgent Core                            │
│                                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  ┌────────────┐  │
│  │   Gateway   │  │   Memory    │  │   Skills   │  │  Sessions  │  │
│  │   Layer     │  │   Store     │  │  Manager   │  │   Store    │  │
│  │             │  │  (SQLite)   │  │ (SKILL.md) │  │  (SQLite)  │  │
│  └──────┬──────┘  └──────┬──────┘  └─────┬──────┘  └─────┬──────┘  │
│         │                │               │               │          │
│  ┌──────┴────────────────┴───────────────┴───────────────┴───────┐  │
│  │                      Agent Core                               │  │
│  │                                                               │  │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌────────────┐  │  │
│  │  │ Message  │  │  Tools   │  │  Provider  │  │  Context   │  │  │
│  │  │ Router   │  │  Engine  │  │  Manager   │  │  Builder   │  │  │
│  │  └──────────┘  └──────────┘  └────────────┘  └────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │    Config    │  │     Auth     │  │       CLI / REPL          │  │
│  │  (YAML+env)  │  │   Manager    │  │  (argparse + rich + PT)  │  │
│  └──────────────┘  └──────────────┘  └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
         │                   │                      │
    ┌────┴──────┐      ┌────┴──────┐          ┌────┴──────┐
    │ Telegram  │      │  Discord  │          │   Slack   │
    │  Adapter  │      │  Adapter  │          │  Adapter  │
    └───────────┘      └───────────┘          └───────────┘
```

## Data Flow

### Message Processing

```
User sends message
       │
       ▼
Platform Adapter ──► Gateway.route()
       │                    │
       │              Auth check (allowlist)
       │                    │
       │              Session lookup/create
       │                    │
       ▼                    ▼
   Reply sent        Agent Core.handle()
       ▲                    │
       │              ┌─────┴──────┐
       │              │   Tools    │
       │              │  Execution │
       │              └─────┬──────┘
       │                    │
       │              LLM Provider call
       │                    │
       └────────────────────┘
```

### Memory Flow

```
Conversation ──► MemoryStore.save(category, content, metadata)
                      │
                      ▼
               SQLite + FTS5 index
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
    search(query)  get_user_   list_recent()
                   profile()
```

## Component Details

### Gateway (`gateway/`)

The gateway manages platform adapters and routes messages to the agent.

- **GatewayConfig** — Allowlist, auth, message limits
- **PlatformAdapter** — Protocol for Telegram, Discord, etc.
- **Message** — Normalized message across all platforms
- **MessageHandler** — Protocol for the agent's response logic

### Memory (`memory/`)

Persistent memory using SQLite with FTS5 full-text search.

- **MemoryStore** — CRUD operations on memory entries
- **FTS5** — Full-text search across all stored content
- **User Profiles** — Per-user profile storage with merge semantics

### Skills (`skills/`)

Modular skill system based on SKILL.md markdown files.

- **SkillManager** — Load, search, create, update, delete skills
- **Front Matter** — YAML metadata in SKILL.md (name, description, tags)
- **Context Injection** — Build prompt context from selected skills

### Sessions (`sessions/`)

Conversation session management with full message history.

- **SessionStore** — SQLite-backed session and message storage
- **FTS5 Search** — Search across all session messages
- **Resume** — Restore full conversation history by session ID

### Config (`config/`)

Type-safe configuration using Pydantic models.

- **NexusConfig** — Root config aggregating all sub-configs
- **YAML + ENV** — Load from file with environment variable overrides
- **AuthManager** — Credential storage, OAuth tokens, pooling

### CLI (`cli/`)

Rich terminal interface with interactive chat and management commands.

- **Interactive REPL** — prompt_toolkit with history and completion
- **Rich Output** — Tables, panels, markdown via Rich library
- **Subcommands** — chat, setup, config, model, tools, skills, sessions, gateway

## Database Schema

### Memory (memory.db)

```sql
memories (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    user_id TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- FTS5 virtual table for full-text search
memories_fts USING fts5(content, category, metadata);

user_profiles (
    user_id TEXT PRIMARY KEY,
    profile TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### Sessions (sessions.db)

```sql
sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    title TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- FTS5 virtual table for message search
messages_fts USING fts5(content);
```

# Provider Setup Guide

## Overview

NexusAgent supports multiple LLM providers through a unified interface.
Configure one or more providers and switch between them seamlessly.

## Supported Providers

### OpenAI

**Models:** GPT-4o, GPT-4, GPT-3.5-turbo, o1, o3

**Setup:**

1. Get an API key from [platform.openai.com](https://platform.openai.com)
2. Set the environment variable:
   ```bash
   export OPENAI_API_KEY="sk-proj-..."
   ```
3. Or add to `.env`:
   ```
   OPENAI_API_KEY=sk-proj-...
   ```

**Config:**
```yaml
model:
  providers:
    openai:
      provider: "openai"
      model: "gpt-4o"
      max_tokens: 4096
      temperature: 0.7
```

### Anthropic

**Models:** Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku

**Setup:**

1. Get an API key from [console.anthropic.com](https://console.anthropic.com)
2. Set the environment variable:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   ```

**Config:**
```yaml
model:
  providers:
    anthropic:
      provider: "anthropic"
      model: "claude-3-5-sonnet-20241022"
      max_tokens: 4096
      temperature: 0.7
```

### Google (Gemini)

**Models:** Gemini 1.5 Pro, Gemini 1.5 Flash

**Setup:**

1. Get an API key from [aistudio.google.com](https://aistudio.google.com)
2. Set the environment variable:
   ```bash
   export GOOGLE_API_KEY="AIza..."
   ```

**Config:**
```yaml
model:
  providers:
    google:
      provider: "google"
      model: "gemini-1.5-pro"
```

### Groq

**Models:** Llama 3, Mixtral (ultra-fast inference)

**Setup:**

1. Get an API key from [console.groq.com](https://console.groq.com)
2. Set the environment variable:
   ```bash
   export GROQ_API_KEY="gsk_..."
   ```

**Config:**
```yaml
model:
  providers:
    groq:
      provider: "groq"
      model: "llama3-70b-8192"
```

### Mistral

**Models:** Mistral Large, Medium, Small

**Setup:**

1. Get an API key from [console.mistral.ai](https://console.mistral.ai)
2. Set the environment variable:
   ```bash
   export MISTRAL_API_KEY="..."
   ```

### Ollama (Local)

**Models:** Any model available in Ollama

**Setup:**

1. Install Ollama: [ollama.ai](https://ollama.ai)
2. Pull a model:
   ```bash
   ollama pull llama3
   ```
3. Ollama runs at `http://localhost:11434` by default

**Config:**
```yaml
model:
  providers:
    ollama:
      provider: "ollama"
      model: "llama3"
      base_url: "http://localhost:11434"
```

### Custom (OpenAI-Compatible)

Any API that implements the OpenAI chat completions format:

```yaml
model:
  providers:
    custom:
      provider: "openai"
      model: "my-model"
      base_url: "https://my-api.example.com/v1"
      api_key: "my-key"
```

## Credential Pooling

For high-throughput scenarios, configure multiple API keys for round-robin:

```python
from config.auth import AuthManager

auth = AuthManager()
auth.add(Credential(name="openai_1", key="sk-key-1"))
auth.add(Credential(name="openai_2", key="sk-key-2"))
auth.create_pool("openai", ["openai_1", "openai_2"])

# Round-robin usage
cred = auth.get_from_pool("openai")
```

## Switching Providers

```bash
# Via CLI
nexus model set anthropic

# Via config
model:
  default_provider: "anthropic"
```

## Troubleshooting

- **Rate limits:** Use credential pooling or increase timeout
- **Connection errors:** Check network and API key validity
- **Model not found:** Verify model name matches provider's list
- **Timeout:** Increase `timeout` in provider config

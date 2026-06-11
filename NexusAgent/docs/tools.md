# Tool Reference

## Overview

NexusAgent includes a suite of built-in tools that the agent can invoke
during conversations. Tools are registered with the agent and executed
safely with configurable sandboxing.

## Built-in Tools

### `web_search`

Search the web for current information.

**Parameters:**
- `query` (str) — Search query
- `num_results` (int) — Number of results (default: 5)

**Returns:** List of search results with title, URL, and snippet.

**Example:**
```
Agent calls: web_search(query="Python 3.13 new features")
Returns: [{title, url, snippet}, ...]
```

### `web_fetch`

Fetch and extract content from a URL.

**Parameters:**
- `url` (str) — URL to fetch
- `extract_mode` (str) — "text", "markdown", "html" (default: "markdown")

**Returns:** Extracted page content as text/markdown.

**Implementation:** Uses Playwright for JS-heavy pages, httpx for simple
HTML, and readability-lxml for content extraction.

### `code_execute`

Execute code in a sandboxed environment.

**Parameters:**
- `language` (str) — Programming language ("python", "javascript", "bash")
- `code` (str) — Code to execute
- `timeout` (int) — Timeout in seconds (default: 30)

**Returns:** stdout, stderr, and exit code.

**Sandboxing:**
- **Docker** (default): Runs in isolated container with no network
- **Local**: Runs with restricted permissions
- **None**: Direct execution (not recommended)

### `file_read`

Read a file from the local filesystem.

**Parameters:**
- `path` (str) — File path
- `offset` (int) — Starting line number (default: 1)
- `limit` (int) — Maximum lines to read (default: 500)

**Returns:** File content with line numbers.

### `file_write`

Write content to a file.

**Parameters:**
- `path` (str) — File path
- `content` (str) — Content to write
- `mode` (str) — "overwrite" or "append" (default: "overwrite")

**Returns:** Confirmation with bytes written.

### `memory`

Search and save to persistent memory.

**Sub-commands:**
- `search(query)` — Full-text search across memories
- `save(category, content)` — Save a new memory
- `get_profile(user_id)` — Get user profile
- `update_profile(user_id, data)` — Update user profile

### `browser`

Automate browser interactions using Playwright.

**Parameters:**
- `action` (str) — "navigate", "click", "type", "screenshot", "evaluate"
- `url` (str) — URL (for navigate)
- `selector` (str) — CSS selector (for click/type)
- `script` (str) — JavaScript (for evaluate)

**Returns:** Screenshot, page content, or evaluation result.

### `skills`

Look up and inject skills into context.

**Sub-commands:**
- `search(query)` — Search available skills
- `inject(skill_ids)` — Inject skills into current context
- `list()` — List all loaded skills

## Creating Custom Tools

### 1. Define the Tool

```python
from typing import Any

async def my_custom_tool(param1: str, param2: int = 10) -> dict[str, Any]:
    """Tool description for the agent.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Dict with tool results.
    """
    # Tool implementation
    return {"result": f"Processed {param1} with {param2}"}
```

### 2. Register the Tool

```python
from agent.tools import ToolRegistry

registry = ToolRegistry()
registry.register(
    name="my_custom_tool",
    fn=my_custom_tool,
    description="Description of what this tool does",
)
```

### 3. Add to Configuration

```yaml
tools:
  custom_tools:
    - name: my_custom_tool
      enabled: true
```

## Tool Safety

- All tools run with configurable approval requirements
- File operations are restricted to allowed directories
- Network access can be blocked in sandboxed environments
- All tool calls are logged in the audit trail
- Rate limiting prevents abuse

## Tool Output Format

All tools return a standardized response:

```python
{
    "success": True,           # Whether the tool succeeded
    "result": "...",           # The tool's output
    "error": None,             # Error message if failed
    "metadata": {              # Optional metadata
        "duration_ms": 123,
        "tool": "web_search"
    }
}
```

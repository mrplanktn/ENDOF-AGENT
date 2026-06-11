# Contributing to NexusAgent

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/nexusagent/nexusagent
cd nexusagent

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install in development mode
pip install -e ".[dev]"
```

## Code Quality

We use **Ruff** for linting and **mypy** for type checking:

```bash
# Lint
ruff check .

# Format
ruff format .

# Type check
mypy .

# Run all checks
ruff check . && ruff format --check . && mypy .
```

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_agent.py -v
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes with type hints and docstrings
4. Add tests for new functionality
5. Ensure all checks pass: `ruff check . && mypy . && pytest`
6. Commit with clear messages: `git commit -m "feat: add amazing feature"`
7. Push and open a Pull Request

## Commit Convention

We follow [Conventional Commits](https://conventionalcommits.org/):

- `feat:` — New feature
- `fix:` — Bug fix
- `docs:` — Documentation only
- `style:` — Code style (no logic change)
- `refactor:` — Code refactoring
- `test:` — Adding/fixing tests
- `chore:` — Maintenance tasks

## Code Style

- Use Python 3.11+ features (type hints with `|`, `match`, etc.)
- All public methods must have docstrings (Google style)
- Prefer `async` for I/O operations
- Use Pydantic models for data validation
- Keep functions focused and under 50 lines

## Architecture Guidelines

- **Modularity**: Each component should be independently testable
- **Protocol-based interfaces**: Use `Protocol` for dependency injection
- **Configuration over code**: Prefer YAML/env config over hardcoded values
- **Error handling**: Always log exceptions; never silently swallow errors

## Reporting Issues

- Use GitHub Issues with the appropriate template
- Include reproduction steps, expected behavior, and actual behavior
- Attach logs if relevant (set `log_level: DEBUG` in config)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

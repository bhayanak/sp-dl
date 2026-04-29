# Contributing to sp-dl

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/sp-dl/sp-dl.git
cd sp-dl
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
# All tests
pytest -v

# With coverage
pytest --cov=sp_dl --cov-report=term-missing

# Specific module
pytest tests/url_parser/ -v
```

## Code Quality

```bash
# Lint
ruff check src/ tests/

# Auto-fix lint issues
ruff check --fix src/ tests/

# Format
ruff format src/ tests/
```

## Project Structure

```
src/sp_dl/
├── cli.py              # Typer CLI commands
├── config.py           # Configuration management
├── constants.py        # URL patterns, API endpoints
├── models.py           # Data models and exceptions
├── url_parser/         # URL detection and parsing
├── auth/               # Authentication providers
├── resolver/           # URL → download target resolution
└── downloader/         # Download engine
```

## Adding a New URL Pattern

1. Create parser in `src/sp_dl/url_parser/`
2. Add regex to `constants.py`
3. Register in `url_parser/detector.py`
4. Add tests in `tests/url_parser/`

## Adding a New Auth Method

1. Create provider in `src/sp_dl/auth/` extending `AuthProvider`
2. Register in `auth/session.py`
3. Add CLI options in `cli.py`
4. Add tests

## Pull Request Guidelines

- Write tests for new features
- Run `ruff check` and `ruff format` before submitting
- Keep PRs focused on a single change
- Update CHANGELOG.md for user-facing changes

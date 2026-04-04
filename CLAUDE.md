# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EasyXT is a modular quantitative trading toolkit for China's QMT (Quick Market Trading) platform. It is **not a single framework** but a set of loosely-coupled modules that can be used independently. The project targets Chinese A-share markets.

## Architecture

Three-layer design with strict unidirectional dependencies (upper calls lower, never the reverse):

```
Application Layer  →  strategies/, 101因子/, gui_app/
Core Layer         →  core/ (config, alpha_analysis, data_manager, path_manager)
Foundation Layer   →  easy_xt/, xtquant/, qstock/
```

### Module independence rules

- **easy_xt** — zero dependencies on other project modules; installable standalone via `pip install -e ./easy_xt`
- **easyxt_backtest** — standalone; does not depend on 101因子
- **101因子平台** — fully independent Streamlit web app
- **strategies/** and **学习实例/** — depend on `easy_xt`

## Key Entry Points

| Module | Entry | Install |
|--------|-------|---------|
| Core API | `from easy_xt import get_api` | `pip install -e ./easy_xt` |
| Backtest | `from easyxt_backtest import BacktestEngine` | Add project root to PYTHONPATH |
| Factor platform | `python 101因子/101因子分析平台/启动增强版.py` | `cd 101因子/101因子分析平台 && pip install -r requirements.txt` |
| Xueqiu follow | `python strategies/xueqiu_follow/start_xueqiu_follow_easyxt.py` | Depends on easy_xt |

## Development Setup

```bash
# 1. xtquant (special version, NOT pip-installable)
#    Download from https://github.com/quant-king299/EasyXT/releases/tag/v1.0.0
#    Extract to project root as xtquant/

# 2. Install core library
pip install -e ./easy_xt

# 3. Install all dependencies
pip install -r requirements.txt

# 4. For backtest, set PYTHONPATH to project root
#    PowerShell: $env:PYTHONPATH += ";C:\path\to\EasyXT"
```

### Environment variables (`.env`)

- `TUSHARE_TOKEN` — for Tushare data downloads
- `XQSHARE_REMOTE_HOST` / `XQSHARE_REMOTE_PORT` — for Mac/Linux remote access
- `XTQUANT_PATH` — if xtquant is installed outside the project root

## Codebase Conventions

### Path management
Always use `core/path_manager.py` instead of ad-hoc `sys.path.insert()`:
```python
from core.path_manager import init_paths, get_project_root
init_paths()  # idempotent, call once at startup
```

### Configuration
Use `core/config/config_manager.py` with dot-notation keys:
```python
from core.config import get_config, set_config
timeout = get_config("data_providers.tdx.timeout", default=30)
```

Strategy-specific configs live in their own `config/` subdirectories (e.g., `strategies/xueqiu_follow/config/unified_config.json`).

### Data source fallback chain
```
QMT (local) → xqshare (remote) → TDX → EastMoney → Tushare
```

DuckDB (`*.ddb`) is the preferred local storage for backtesting (10x faster). It is optional — the system falls back to QMT/Tushare.

### API patterns in easy_xt
- Lazy imports via `__getattr__` to avoid circular dependencies
- Singleton pattern: `get_api()`, `get_extended_api()`, `get_advanced_api()`
- All trading goes through `easy_xt/trade_api.py` → `easy_xt/api.py` → QMT

## Build System

- Uses **flit** (`pyproject.toml` with `flit_core` backend)
- `easy_xt/` has its own `pyproject.toml` for standalone install
- No test framework is configured (no pytest.ini, no conftest.py)
- No CI/CD pipeline

## Language

All documentation, comments, log messages, and user-facing strings are in **Chinese**. Maintain this convention.

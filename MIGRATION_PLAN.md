# SOC-Claw Project Reorganization Plan

## Executive Summary

This plan details the comprehensive reorganization of the SOC-Claw project structure to improve maintainability, clarity, and consistency. The reorganization addresses current structural issues including typos, inconsistent naming, scattered files, and unclear separation of concerns.

## Current Issues Identified

1. **Typo**: `assests/` should be `assets/`
2. **Inconsistent naming**: `backend/routers/` vs `backend/routes/` serve similar purposes
3. **Scattered root files**: Config, docs, and diagrams mixed at root level
4. **Mixed concerns**: `soc_claw/` contains both app code and mock data
5. **Unclear separation**: `data/` vs `soc_claw/mock_data/` overlap
6. **Inconsistent naming**: Some dirs use underscores (`mock_data`), others don't (`frontend`)
7. **Missing organization**: No clear separation between core app, infrastructure, and utilities

## Target Structure

```
SoC-Claw/
├── assets/                    # Images, screenshots, diagrams
├── config/                    # All configuration files
│   └── routing.yaml
├── data/                      # All data files
│   ├── mock/                 # Mock/test data
│   └── benchmark/            # Benchmark results
├── docs/                      # All documentation
│   ├── reviews/
│   └── *.md files
├── infrastructure/            # Docker, deployment, scripts
│   ├── docker/
│   │   ├── Dockerfile
│   │   └── docker-compose.yml
│   └── scripts/
├── models/                    # ML models
├── soc_claw/                  # Core application code
│   ├── agents/               # Agent implementations
│   ├── api/                  # API layer (renamed from backend)
│   │   ├── routes/          # Unified routing
│   │   ├── auth.py
│   │   ├── security.py
│   │   └── server.py
│   ├── connectors/           # External system connectors
│   ├── core/                 # Core business logic
│   │   ├── audit.py
│   │   ├── cache.py
│   │   ├── pipeline.py
│   │   ├── routing.py
│   │   ├── schemas.py
│   │   ├── telemetry.py
│   │   └── utils.py
│   ├── frontend/             # UI components
│   │   ├── static/
│   │   ├── styles/
│   │   └── templates/
│   ├── llm/                  # LLM integration
│   └── tools/                # Tool implementations
├── tests/                     # All tests
└── graphify-out/             # Knowledge graph output
```

## Detailed Migration Steps

### Phase 1: Directory Structure Changes

#### 1.1 Fix Typo and Create New Directories
```bash
# Fix typo
mv assests assets

# Create new directories
mkdir -p infrastructure/docker
mkdir -p infrastructure/scripts
mkdir -p data/mock
mkdir -p data/benchmark
mkdir -p config
```

#### 1.2 Move Configuration Files
```bash
# Move config from soc_claw/config to config/
mv soc_claw/config/routing.yaml config/
rmdir soc_claw/config
```

#### 1.3 Move Data Files
```bash
# Move mock data to data/mock/
mv soc_claw/mock_data/* data/mock/
rmdir soc_claw/mock_data

# Move benchmark results to data/benchmark/
mv soc_claw/benchmark/results/* data/benchmark/
rmdir soc_claw/benchmark/results
```

#### 1.4 Move Infrastructure Files
```bash
# Move Docker files
mv Dockerfile infrastructure/docker/
mv docker-compose.yml infrastructure/docker/

# Move scripts
mv scripts/* infrastructure/scripts/
rmdir scripts
```

#### 1.5 Move Documentation
```bash
# Move docs to docs/ (already in place, just verify)
# Move diagrams to assets/
mv *.drawio assets/
mv *.png assets/
```

#### 1.6 Reorganize soc_claw Structure
```bash
# Rename backend to api
mv soc_claw/backend soc_claw/api

# Create core directory
mkdir soc_claw/core

# Move core files to core/
mv soc_claw/audit.py soc_claw/core/
mv soc_claw/cache.py soc_claw/core/
mv soc_claw/pipeline.py soc_claw/core/
mv soc_claw/routing.py soc_claw/core/
mv soc_claw/schemas.py soc_claw/core/
mv soc_claw/telemetry.py soc_claw/core/
mv soc_claw/utils.py soc_claw/core/
mv soc_claw/logging_config.py soc_claw/core/

# Merge routers and routes
mv soc_claw/api/routes/* soc_claw/api/routes/
# Note: backend/routes and backend/routers will be merged
```

### Phase 2: Import Statement Updates

#### 2.1 Core Module Updates
All imports referencing core modules need to be updated:

**Pattern**: `from soc_claw.{module}` → `from soc_claw.core.{module}`

Files to update:
- `soc_claw/api/server.py`
- `soc_claw/api/routers/api.py`
- `soc_claw/api/routers/auth.py`
- `soc_claw/api/routers/pages.py`
- `soc_claw/api/routes/siem_webhook.py`
- `soc_claw/api/routes/batch_api.py`
- `soc_claw/agents/triage_agent.py`
- `soc_claw/agents/verifier_agent.py`
- `soc_claw/agents/response_agent.py`
- `soc_claw/llm/caller.py`
- `soc_claw/pipeline.py` (now in core/)
- `soc_claw/benchmark/harness.py`
- `soc_claw/connectors/*.py`
- `soc_claw/tools/*.py`

#### 2.2 API Module Updates
**Pattern**: `from soc_claw.backend` → `from soc_claw.api`

Files to update:
- All files importing from `soc_claw.backend`
- `soc_claw/api/server.py` (self-references)
- Test files

#### 2.3 Data Path Updates
**Pattern**: Update `DATA_DIR` and path references in tools

Files to update:
- `soc_claw/tools/ip_reputation.py`: `DATA_DIR = Path(__file__).parent.parent / "mock_data"` → `DATA_DIR = Path(__file__).parent.parent.parent / "data" / "mock"`
- `soc_claw/tools/asset_lookup.py`: Same pattern
- `soc_claw/tools/mitre_lookup.py`: Same pattern
- `soc_claw/benchmark/harness.py`: Update data directory references

#### 2.4 Config Path Updates
**Pattern**: Update `CONFIG_DIR` references

Files to update:
- `soc_claw/core/routing.py`: `CONFIG_DIR = Path(__file__).parent / "config"` → `CONFIG_DIR = Path(__file__).parent.parent.parent / "config"`

### Phase 3: Configuration File Updates

#### 3.1 pyproject.toml Updates
```toml
# Update package includes
[tool.hatch.build.targets.wheel.force-include]
"data/mock" = "soc_claw/data/mock"
"config" = "soc_claw/config"
"soc_claw/frontend/templates" = "soc_claw/frontend/templates"
```

#### 3.2 Dockerfile Updates
```dockerfile
# Update COPY paths
COPY infrastructure/docker/pyproject.toml ./pyproject.toml
COPY infrastructure/docker/uv.lock ./uv.lock
COPY soc_claw/ /app/soc_claw/
COPY config/ /app/config/
COPY data/ /app/data/
```

#### 3.3 docker-compose.yml Updates
```yaml
# Update volume mounts
volumes:
  - ./data/benchmark:/app/data/benchmark
  - ./.secrets/bluelantern-gcs.json:/app/.secrets/bluelantern-gcs.json:ro
```

#### 3.4 .env.example Updates
Update path references in comments and default values.

### Phase 4: Documentation Updates

#### 4.1 README.md Updates
- Update all path references
- Update directory structure documentation
- Update quick start commands

#### 4.2 AGENTS.md Updates
- Update all path references
- Update architecture notes
- Update configuration sections

#### 4.3 SETUP.md Updates
- Update installation instructions
- Update path references
- Update configuration examples

### Phase 5: Test Updates

#### 5.1 Test Import Updates
Update all test files to use new import paths:
- `tests/test_tools_smoke.py`
- `tests/test_*.py`

#### 5.2 Test Path Updates
Update any hardcoded paths in test files.

### Phase 6: Validation and Testing

#### 6.1 Import Validation
```bash
# Check for broken imports
python -c "import soc_claw"
python -c "from soc_claw.api import server"
python -c "from soc_claw.core import pipeline"
python -c "from soc_claw.tools import ip_reputation"
```

#### 6.2 Test Suite Validation
```bash
# Run all tests
pytest
```

#### 6.3 Application Startup Validation
```bash
# Test server startup
python -m soc_claw.api.server
```

#### 6.4 Benchmark Validation
```bash
# Test benchmark
python -m soc_claw.benchmark.harness 5
```

## Risk Mitigation

### Backup Strategy
1. Create git commit before starting: `git commit -am "Pre-reorganization backup"`
2. Create backup branch: `git branch backup-before-reorg`
3. Consider creating tarball of entire project: `tar -czf soc-claw-backup.tar.gz .`

### Rollback Plan
If issues arise:
1. Git checkout backup branch: `git checkout backup-before-reorg`
2. Or restore from tarball: `tar -xzf soc-claw-backup.tar.gz`

### Testing Strategy
1. Test after each phase
2. Run full test suite after completion
3. Manual testing of critical paths
4. Docker build and run testing

## Import Statement Mapping

### Core Module Imports
| Old Import | New Import |
|------------|------------|
| `from soc_claw.audit import` | `from soc_claw.core.audit import` |
| `from soc_claw.cache import` | `from soc_claw.core.cache import` |
| `from soc_claw.pipeline import` | `from soc_claw.core.pipeline import` |
| `from soc_claw.routing import` | `from soc_claw.core.routing import` |
| `from soc_claw.schemas import` | `from soc_claw.core.schemas import` |
| `from soc_claw.telemetry import` | `from soc_claw.core.telemetry import` |
| `from soc_claw.utils import` | `from soc_claw.core.utils import` |
| `from soc_claw.logging_config import` | `from soc_claw.core.logging_config import` |

### API Module Imports
| Old Import | New Import |
|------------|------------|
| `from soc_claw.backend.server import` | `from soc_claw.api.server import` |
| `from soc_claw.backend.auth import` | `from soc_claw.api.auth import` |
| `from soc_claw.backend.security import` | `from soc_claw.api.security import` |
| `from soc_claw.backend.routers import` | `from soc_claw.api.routers import` |
| `from soc_claw.backend.routes import` | `from soc_claw.api.routes import` |

### Data Path Updates
| File | Old Path | New Path |
|------|----------|----------|
| `tools/ip_reputation.py` | `Path(__file__).parent.parent / "mock_data"` | `Path(__file__).parent.parent.parent / "data" / "mock"` |
| `tools/asset_lookup.py` | `Path(__file__).parent.parent / "mock_data"` | `Path(__file__).parent.parent.parent / "data" / "mock"` |
| `tools/mitre_lookup.py` | `Path(__file__).parent.parent / "mock_data"` | `Path(__file__).parent.parent.parent / "data" / "mock"` |
| `benchmark/harness.py` | `Path(__file__).parent.parent / "mock_data"` | `Path(__file__).parent.parent.parent / "data" / "mock"` |
| `core/routing.py` | `Path(__file__).parent / "config"` | `Path(__file__).parent.parent.parent / "config"` |

## Configuration File Updates

### pyproject.toml Changes
```toml
[tool.hatch.build.targets.wheel.force-include]
"data/mock" = "soc_claw/data/mock"
"config" = "soc_claw/config"
"soc_claw/frontend/templates" = "soc_claw/frontend/templates"
```

### Dockerfile Changes
```dockerfile
# Update paths
COPY infrastructure/docker/pyproject.toml ./pyproject.toml
COPY infrastructure/docker/uv.lock ./uv.lock
COPY soc_claw/ /app/soc_claw/
COPY config/ /app/config/
COPY data/ /app/data/
```

### docker-compose.yml Changes
```yaml
volumes:
  - ./data/benchmark:/app/data/benchmark
  - ./.secrets/bluelantern-gcs.json:/app/.secrets/bluelantern-gcs.json:ro
```

## Execution Order

1. **Pre-migration**: Create backup and commit
2. **Phase 1**: Directory structure changes
3. **Phase 2**: Import statement updates
4. **Phase 3**: Configuration file updates
5. **Phase 4**: Documentation updates
6. **Phase 5**: Test updates
7. **Phase 6**: Validation and testing
8. **Post-migration**: Final commit and testing

## Success Criteria

- All imports resolve correctly
- All tests pass
- Application starts without errors
- Benchmark runs successfully
- Docker build succeeds
- No broken path references
- Documentation is accurate

## Estimated Time

- Phase 1: 30 minutes
- Phase 2: 2 hours
- Phase 3: 1 hour
- Phase 4: 1 hour
- Phase 5: 1 hour
- Phase 6: 2 hours

**Total**: ~7.5 hours

## Notes

- This reorganization maintains backward compatibility where possible
- The `soc_claw.utils` module already acts as a re-export shim, so it will continue to work
- Some imports may need to be updated in external dependencies
- The reorganization follows Python best practices for package structure
- All changes are designed to be reversible via git if needed
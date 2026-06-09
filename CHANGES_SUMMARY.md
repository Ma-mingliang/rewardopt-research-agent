# Changes Summary: Version Tracking System

## Overview

Added comprehensive version tracking system to the optimizer that logs every candidate/version with full context immediately after generation.

## Files Created

### 1. `research_agent/core/version_tracker.py`
New module that provides:
- `VersionTracker` class for logging versions
- Persistent version counter across runs
- Output to CHANGELOG.md (human-readable)
- Output to tried_methods.jsonl (machine-readable)
- Real-time stdout output with flush=True

### 2. `run_optimizer.py`
Standalone optimizer runner with version tracking:
- Iterative method selection from paper pool
- Real-time version logging
- Configurable batch size and max iterations
- Mock LLM support for testing

### 3. `VERSION_TRACKING.md`
Documentation for the version tracking system

### 4. `CHANGES_SUMMARY.md`
This file

## Files Modified

### 1. `research_agent/core/executor.py`
- Added import for VersionTracker and helper functions
- Integrated version tracking into `_execute_optimizer_phase()`
- Each candidate now logs:
  - version_id (sequential, persistent)
  - candidate_id
  - reward_formula
  - modified_files with line ranges
  - metrics_before (baseline)
  - metrics_after (after evaluation)
  - accepted/rejected status
  - rejection_reason or error_traceback
  - source_methods from paper pool
  - timestamp

### 2. `research_agent/interfaces/cli.py`
- Added version tracking summary output to `run-iteration` command
- Real-time iteration progress display with flush=True

## Tracked Fields

| Field | Description | Example |
|-------|-------------|---------|
| `version_id` | Sequential version ID | `v0001`, `v0002`, ... |
| `candidate_id` | Optimizer candidate ID | `reward_c001` |
| `reward_formula` | Reward formula or change description | `"Add potential-based reward"` |
| `modified_files` | List of modified files | `[{"file": "main.py", "line_range": [1, 5]}]` |
| `metrics_before` | Baseline metrics | `{"loss": {"mean": 2.17}, "reward": {"mean": 0.44}}` |
| `metrics_after` | Metrics after eval | `{"loss": {"mean": 1.5}, "reward": {"mean": 0.52}}` |
| `accepted` | Whether accepted | `true` / `false` |
| `rejection_reason` | Reason for rejection | `"empty_patch"`, `"no_improvement"` |
| `error_traceback` | Error traceback | `"Traceback..."` |
| `source_methods` | Source method IDs | `["method_id_1", "method_id_2"]` |
| `timestamp` | ISO 8601 timestamp | `"2026-06-06T10:35:13.605748+00:00"` |
| `description` | Human-readable description | `"Add potential-based reward shaping"` |

## Output Files

### CHANGELOG.md
Location: `<project>/.research-agent/CHANGELOG.md`

Human-readable markdown with detailed entries for each version:
- Timestamp and version ID
- Candidate ID and status (ACCEPTED/REJECTED)
- Reward formula or change description
- Modified files with line ranges
- Metrics before and after
- Rejection reason or error traceback
- Source methods from paper pool

### tried_methods.jsonl
Location: `<project>/.research-agent/logs/tried_methods.jsonl`

Machine-readable JSONL format, one record per version.

### version_counter.json
Location: `<project>/.research-agent/logs/version_counter.json`

Persistent version counter for sequential version IDs.

## Usage Examples

### Run Optimizer
```bash
# Using Anaconda Python
E:/Anaconda/python.exe run_optimizer.py --project test_accept --mock-llm --max-iterations 5

# Options:
#   --project PATH       Project root path (required)
#   --max-iterations N   Max iterations (default: unlimited)
#   --mock-llm           Skip LLM calls
#   --batch-size N       Methods per batch (default: 2)
```

### Run Single Iteration
```bash
E:/Anaconda/python.exe -m research_agent.interfaces.cli run-iteration --project test_accept --mock-llm
```

### Monitor Progress
```bash
# Watch CHANGELOG.md
tail -f test_accept/.research-agent/CHANGELOG.md

# Watch tried_methods.jsonl
tail -f test_accept/.research-agent/logs/tried_methods.jsonl

# Parse accepted versions
cat test_accept/.research-agent/logs/tried_methods.jsonl | jq 'select(.accepted == true)'
```

## Example Output

```
================================================================================
[VERSION] v0001 | reward_c001 | REJECTED
================================================================================
Timestamp: 2026-06-06T10:35:13.605748+00:00
Reward Formula:
No-op candidate (mock-llm mode)

Metrics Before: loss=2.1700, reward=0.4390
Rejection:      empty_patch
================================================================================
```

## Key Features

1. **Immediate Logging**: Each version is logged immediately after generation
2. **Persistent Counter**: Version IDs persist across runs
3. **Multiple Formats**: CHANGELOG.md (human), tried_methods.jsonl (machine), stdout (real-time)
4. **Full Context**: All required fields are tracked
5. **flush=True**: Real-time output for monitoring
6. **Error Tracking**: Full error tracebacks logged
7. **Source Tracking**: Links back to paper pool methods

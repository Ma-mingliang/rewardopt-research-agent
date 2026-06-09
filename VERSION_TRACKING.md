# Version Tracking System

The optimizer now includes a comprehensive version tracking system that logs every candidate/version with full context.

## Output Files

### 1. CHANGELOG.md (Human-readable)
Location: `<project>/.research-agent/CHANGELOG.md`

Contains detailed entries for each candidate version:
- Timestamp and version ID
- Candidate ID and status (ACCEPTED/REJECTED)
- Reward formula or change description
- Modified files with line ranges
- Metrics before (baseline) and after evaluation
- Rejection reason (if rejected)
- Error traceback (if error occurred)
- Source methods from paper pool

### 2. tried_methods.jsonl (Machine-readable)
Location: `<project>/.research-agent/logs/tried_methods.jsonl`

JSONL format with one record per version:
```json
{
  "timestamp": "2026-06-06T10:35:13.605748+00:00",
  "version_id": "v0001",
  "candidate_id": "reward_c001",
  "reward_formula": "...",
  "modified_files": [{"file": "main.py", "line_range": [1, 5]}],
  "metrics_before": {"loss": {"mean": 2.17, ...}, "reward": {"mean": 0.439, ...}},
  "metrics_after": {"loss": {"mean": 1.5, ...}, "reward": {"mean": 0.52, ...}},
  "accepted": true,
  "rejection_reason": null,
  "error_traceback": null,
  "source_methods": ["method_id_1", "method_id_2"],
  "description": "..."
}
```

### 3. stdout (Real-time)
All version information is printed to stdout with `flush=True` for real-time monitoring.

## Usage

### Run Optimizer with Version Tracking

```bash
# Using Anaconda Python (recommended)
E:/Anaconda/python.exe run_optimizer.py --project test_accept --mock-llm --max-iterations 5

# Options:
#   --project PATH       Project root path (required)
#   --max-iterations N   Max iterations to run (default: unlimited)
#   --mock-llm           Skip LLM calls, use no-op fallback
#   --batch-size N       Methods per batch (default: 2)
```

### Run Single Iteration

```bash
E:/Anaconda/python.exe -m research_agent.interfaces.cli run-iteration --project test_accept --mock-llm
```

### Monitor Progress

```bash
# Watch CHANGELOG.md in real-time
tail -f test_accept/.research-agent/CHANGELOG.md

# Watch tried_methods.jsonl
tail -f test_accept/.research-agent/logs/tried_methods.jsonl

# Parse tried_methods.jsonl
cat test_accept/.research-agent/logs/tried_methods.jsonl | jq '.accepted'
```

## Tracked Fields

| Field | Description |
|-------|-------------|
| `version_id` | Sequential version identifier (v0001, v0002, ...) |
| `candidate_id` | Candidate ID from optimizer |
| `reward_formula` | Reward formula or change description |
| `modified_files` | List of modified file locations with line ranges |
| `metrics_before` | Baseline metrics before this version |
| `metrics_after` | Metrics after evaluation (null if skipped) |
| `accepted` | Whether this version was accepted |
| `rejection_reason` | Reason for rejection (if rejected) |
| `error_traceback` | Error traceback (if error occurred) |
| `source_methods` | Source method IDs from paper pool |
| `timestamp` | ISO 8601 timestamp |
| `description` | Human-readable description |

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

## Files Modified

The following files were modified to implement version tracking:

1. `research_agent/core/version_tracker.py` - New version tracker module
2. `research_agent/core/executor.py` - Integrated version tracking into optimizer phase
3. `research_agent/interfaces/cli.py` - Added version tracking to run-iteration command
4. `run_optimizer.py` - New standalone optimizer runner with version tracking

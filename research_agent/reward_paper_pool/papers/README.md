# Reward Paper Pool - Papers Download

## Overview

The `papers/` directory contains 435 academic PDFs and 150 markitdown-converted markdown files, organized by reward shaping category. This directory is excluded from git (too large) and distributed as a GitHub Release asset.

## Download

Download the archive from GitHub Releases:

```
https://github.com/Ma-mingliang/rewardopt-research-agent/releases
```

File: `reward_paper_pool_papers.zip` (~814MB)

## Extraction

Extract to the project root so that the papers land at the correct path:

```bash
# From the research-agent project root:
cd research-agent

# Extract (preserves directory structure)
unzip reward_paper_pool_papers.zip

# Or on Windows:
# Right-click → Extract All → select research-agent root
```

After extraction, the directory structure should be:

```
research_agent/reward_paper_pool/papers/
├── all_sources/          # PDFs from all sources (arxiv + openreview + others)
│   ├── by_category/      # 8 categories, 139 papers
│   │   ├── A_potential_based_reward/
│   │   ├── B_safety_constraint_reward/
│   │   ├── C_curriculum_subgoal_reward/
│   │   ├── D_adaptive_dynamic_reward/
│   │   ├── E_hierarchical_reward/
│   │   ├── F_residual_aware_reward/
│   │   ├── G_llm_reward_generation/
│   │   └── H_learned_preference_reward/
│   └── manifest.csv      # Paper metadata
├── arxiv/                # PDFs from arxiv only
│   ├── by_category/      # 8 categories, 110 papers
│   └── manifest.csv
└── md/                   # Markitdown-converted markdown files
    ├── by_category/      # 8 categories, 150 markdown files
    └── manifest.md
```

## Verify

After extraction, verify the papers are in place:

```bash
# Count PDFs
find research_agent/reward_paper_pool/papers -name "*.pdf" | wc -l
# Expected: 435

# Count MD files
find research_agent/reward_paper_pool/papers/md -name "*.md" | wc -l
# Expected: 150

# Check category structure
ls research_agent/reward_paper_pool/papers/all_sources/by_category/
# Expected: 8 category directories (A through H)
```

## Contents

| Directory | Content | Count | Size |
|-----------|---------|-------|------|
| `all_sources/by_category/` | PDFs (all sources) | 139 | ~545MB |
| `arxiv/by_category/` | PDFs (arxiv only) | 110 | ~390MB |
| `md/by_category/` | Markdown (markitdown) | 150 | ~13MB |

### Categories

| Category | Description |
|----------|-------------|
| `A_potential_based_reward` | Potential-Based Reward Shaping (PBRS) |
| `B_safety_constraint_reward` | Safety Constraint Reward |
| `C_curriculum_subgoal_reward` | Curriculum / Subgoal Reward |
| `D_adaptive_dynamic_reward` | Adaptive / Dynamic Reward |
| `E_hierarchical_reward` | Hierarchical Reward |
| `F_residual_aware_reward` | Residual-Aware Reward |
| `G_llm_reward_generation` | LLM-Based Reward Generation |
| `H_learned_preference_reward` | Learned Preference Reward |

## Note

The `_download_cache/` directories are excluded from the archive to save space. These contain duplicate copies of the PDFs used during the download process. The `by_category/` directories contain the final organized copies.

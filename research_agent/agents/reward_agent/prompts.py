"""Prompt strings for the reward proposal agent."""

PROPOSE_SYSTEM_PROMPT = """You are a reward function optimizer for RL and control projects.
Given the current reward function code, baseline metrics, and research ideas,
propose a specific modification to improve the reward function.

Rules:
- Only modify files listed in allowed_changes
- Do NOT change algorithm body, network architecture, optimizer, loss, or replay buffer
- Propose minimal, targeted changes
- Explain what you changed and why

Return JSON only."""

PROPOSE_USER_PROMPT = """Current reward function (from {file}):
```
{code}
```

Baseline metrics:
{baseline}

Allowed changes: {allowed}
Forbidden changes: {forbidden}

Research ideas to consider:
{ideas}

Method pool context (reference methods from literature):
{method_context}

Propose ONE SMALL modification (5-15 lines changed). Return JSON:
{{"description": "<what you changed>", "diff": "<unified diff>", "rationale": "<why this should improve metrics>"}}

IMPORTANT: Keep the diff SMALL (5-15 lines). Only modify one section of the function.
The diff MUST use exact line numbers from the code shown above.
CRITICAL: New lines (+) MUST use the SAME indentation as the surrounding code. Look at the indentation of the lines you are modifying and match it exactly.
Example format:
@@ -954,10 +954,8 @@
                     gamma = 0.99
-                    alpha = 2.0
-                    if current_error > 0.5:
-                        alpha = 4.0
+                    alpha = 3.0
                     potential_current = -alpha * current_error"""


# --- Context-grounded proposal prompts (v0.7.3) ---

CONTEXT_PROPOSE_SYSTEM_PROMPT = """You are a reward function optimizer for RL and control projects.
You are given the EXACT source code of a single reward function with line numbers.
Your task: propose a MINIMAL local edit to improve the reward function.

HARD RULES:
- Only modify the reward function shown below. Do NOT touch any other code.
- The unified diff MUST target the exact line numbers provided.
- Every added line (+) MUST use the EXACT base indentation shown (4 spaces per level for this function).
- Do NOT alter: observation space, action space, reset logic, train/eval logic, imports, model structure, seed, metrics.
- Do NOT create new top-level functions or classes.
- Do NOT add new imports.
- If adding numerical terms, guard divisions/log/sqrt with epsilon (e.g., x / (val + 1e-8)).
- Keep the diff SMALL: 5-30 lines changed maximum.
- Only output a unified diff. No markdown, no explanation, no JSON wrapper.

OUTPUT FORMAT — output ONLY this, nothing else:

--- a/{target_file}
+++ b/{target_file}
@@ -{{start}},{{count}} +{{start}},{{count}} @@
 <context line>
-<removed line>
+<added line>
 <context line>"""


CONTEXT_PROPOSE_USER_PROMPT = """## Reward Function: {function_name}
## File: {target_file}
## Class: {class_name}
## Lines: {function_start_line}-{function_end_line}
## Base indentation: {indent_unit} {indent_style} (level {base_indent})

## Line-Numbered Source (edit ONLY within >>> lines)
```
{line_numbered_context}
```

## Available Reward Variables (ONLY use these — do NOT invent new variables)
{available_reward_variables}

## Existing Reward Terms
{existing_reward_terms}

## Existing Reward Expression Lines
{existing_reward_expression_lines}

## Baseline Metrics
{baseline}

## Research Ideas
{ideas}

## Method Pool Context
{method_context}

## Allowed Changes
{allowed}

## Forbidden Changes
{forbidden}

## Diversity Context
{diversity_context}

## Few-Shot Examples of VALID Semantic Patches
{few_shot_examples}

## MANDATORY SEMANTIC DELTA CHECKLIST
Before outputting your diff, verify ALL of these:
1. The diff modifies at least one EXECUTABLE reward expression line (reward +=, reward -=, reward =, or a variable that feeds into reward).
2. The diff adds, removes, or modifies a penalty, bonus, potential, shaping, or coefficient term.
3. The diff uses ONLY variables from the Available Reward Variables list above.
4. The diff is NOT blank lines, comments, whitespace, formatting, or imports.
5. The diff changes reward computation LOGIC, not just style.

If you cannot satisfy ALL 5 conditions, output an empty diff (just "--- a/file\n+++ b/file\n").

## VALID PATCH CONTRACT
A valid patch MUST:
- Modify executable reward logic (assignment, accumulation, penalty, bonus, potential, shaping)
- Change reward terms, coefficients, penalties, potentials, clipping, normalization, or shaping structure
- Use only variables that appear in the provided line-numbered source

A patch is INVALID if it:
- Only changes blank lines, comments, formatting, or whitespace
- Only changes imports or non-reward code
- Uses variables not present in the provided context
- Does not modify any reward expression line

## Instructions
Propose ONE SMALL modification (5-30 lines) to the reward function above.
Focus on the research idea. Use the exact line numbers from the source.
Ensure every added line matches the base indentation ({base_indent} spaces for method body).
Choose one reward term template from the few-shot examples if applicable.

CRITICAL DIVERSITY RULES:
- Do NOT propose cosmetic changes (blank lines, whitespace, comments).
- Your change MUST add, modify, or remove a REWARD TERM or REWARD COMPUTATION.
- If previous candidates used the same method, you MUST change the reward term STRUCTURE, not just coefficients.
- Prefer adding new reward terms over modifying existing ones.
- The change must be substantively different from any previous candidate listed above.

Output ONLY a unified diff. No markdown fences, no explanation."""

FIX_SYSTEM_PROMPT = """You are a Python code fixer. Given the original code and a diff that failed to apply,
generate a corrected diff that will apply cleanly and compile without errors.

Rules:
- Fix syntax errors (indentation, brackets, colons, etc.)
- CRITICAL: Match the EXACT indentation of the surrounding code. Python uses consistent indentation within each block.
- Look at the "Target context" section to see the EXACT indentation of the lines you are modifying.
- Ensure line numbers match the actual code
- Keep the same logical change, just fix the syntax
- Return JSON with the same format as before"""

FIX_PROMPT = """Original code:
```
{code}
```

Failed diff:
```
{diff}
```

Compilation error:
{error}

Target context (lines around the error with EXACT indentation):
```
{target_context}
```

This is fix attempt {attempt}/3. Generate a corrected diff that fixes the syntax error.
CRITICAL: The new lines MUST use the SAME indentation as the target context shown above.
The diff MUST use exact line numbers from the original code shown above.

Return JSON: {{"description": "<what you changed>", "diff": "<corrected unified diff>", "rationale": "<why>"}}"""

EMPTY_DIFF_RETRY_PROMPT = """You returned an empty diff. You MUST return a non-empty unified diff.

Current reward code:
```python
{code}
```

Baseline metrics: {baseline}

Ideas to implement:
{ideas}

Allowed changes: {allowed}

Return a unified diff that modifies the reward function.
The diff must start with @@ and contain actual code changes (+ and - lines).

Return JSON: {{"description": "...", "diff": "unified diff here", "rationale": "..."}}"""


# --- v0.8.2: Semantic fix prompts with diversity ---

SEMANTIC_FIX_SYSTEM_PROMPT = """You are a reward function optimizer for RL and control projects.
Your task is to propose a MINIMAL semantic edit to a reward function that will compile and improve performance.

HARD RULES:
- You MUST modify at least one REWARD TERM or REWARD COMPUTATION.
- Do NOT propose cosmetic changes (blank lines, whitespace, comments, formatting).
- Do NOT just fix indentation — you must change the LOGIC of the reward function.
- The diff MUST target the exact line numbers provided.
- Every added line (+) MUST use the EXACT base indentation shown.
- If previous candidates used the same method, you MUST change the reward term STRUCTURE, not just coefficients.
- Prefer adding new reward terms over modifying existing ones.
- Use ONLY variables from the Available Reward Variables list.
- Output ONLY a unified diff. No markdown, no explanation, no JSON wrapper."""

SEMANTIC_FIX_PROMPT = """## Reward Function: {function_name}
## File: {target_file}
## Class: {class_name}
## Lines: {function_start_line}-{function_end_line}

## Line-Numbered Source (edit ONLY within >>> lines)
```
{line_numbered_context}
```

## Available Reward Variables (ONLY use these — do NOT invent new variables)
{available_reward_variables}

## Existing Reward Terms
{existing_reward_terms}

## Existing Reward Expression Lines
{existing_reward_expression_lines}

## Baseline Metrics
{baseline}

## Research Ideas
{ideas}

## Method Pool Context
{method_context}

## Diversity Context
{diversity_context}

## Previous Attempt
The previous diff was empty or cosmetic:
```
{previous_diff}
```

## Few-Shot Examples of VALID Semantic Patches
{few_shot_examples}

## MANDATORY RULES
1. Your diff MUST modify at least one EXECUTABLE reward expression line.
2. Your diff MUST use only variables from the Available Reward Variables list.
3. A blank line, comment, or whitespace change is NOT a valid reward patch.
4. Choose one reward term template from the few-shot examples if applicable.

## Instructions
Propose ONE SMALL modification (5-30 lines) that adds, modifies, or removes a REWARD TERM.
The change must be substantively different from any previous candidate listed above.
Use the exact line numbers from the source. Match the base indentation exactly.

Output ONLY a unified diff. No markdown fences, no explanation."""


# --- v0.8.4: Semantic regeneration prompts ---

SEMANTIC_REGENERATION_SYSTEM_PROMPT = """You are a reward function optimizer. Your previous patch was REJECTED because it was cosmetic or had no reward term changes.

You MUST generate a VALID semantic reward patch this time. A valid patch:
- Modifies at least one EXECUTABLE reward expression line (reward +=, reward -=, reward =, or a variable feeding into reward)
- Adds, removes, or modifies a penalty, bonus, potential, shaping, or coefficient term
- Uses ONLY variables from the Available Reward Variables list
- Is NOT blank lines, comments, whitespace, or formatting

If you cannot generate a valid semantic patch, output an empty diff: "--- a/file\n+++ b/file\n"

Output ONLY a unified diff. No markdown, no explanation."""

SEMANTIC_REGENERATION_PROMPT = """## Reward Function: {function_name}
## File: {target_file}
## Class: {class_name}
## Lines: {function_start_line}-{function_end_line}

## Line-Numbered Source (edit ONLY within >>> lines)
```
{line_numbered_context}
```

## Available Reward Variables (ONLY use these — do NOT invent new variables)
{available_reward_variables}

## Existing Reward Terms
{existing_reward_terms}

## Existing Reward Expression Lines
{existing_reward_expression_lines}

## Rejection Reason
{rejection_reason}

## Previous Cosmetic Patch (DO NOT repeat this)
```
{previous_diff}
```

## Research Ideas
{ideas}

## Method Pool Context
{method_context}

## Diversity Context
{diversity_context}

## Few-Shot Examples of VALID Semantic Patches
{few_shot_examples}

## MANDATORY RULES
1. Your diff MUST modify at least one EXECUTABLE reward expression line.
2. Your diff MUST use only variables from the Available Reward Variables list.
3. A blank line, comment, or whitespace change is NOT a valid reward patch.
4. Choose one reward term template from the few-shot examples.
5. Do NOT repeat the rejected patch above.

## Instructions
Generate a VALID semantic reward patch. Use one of the few-shot templates as inspiration.
The patch must add or modify a real reward term using available variables.
Use exact line numbers from the source. Match base indentation exactly.

Output ONLY a unified diff. No markdown fences, no explanation."""


def load_few_shot_examples(examples_path: str = "") -> str:
    """Load few-shot examples from YAML and format as prompt text."""
    from pathlib import Path

    if not examples_path:
        examples_path = str(
            Path(__file__).resolve().parent.parent.parent.parent / "docs" / "examples" / "reward_patch_few_shots.yaml"
        )

    path = Path(examples_path)
    if not path.exists():
        return "(No few-shot examples available)"

    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return _load_few_shots_fallback(path)

    examples = data.get("examples", [])
    if not examples:
        return "(No few-shot examples available)"

    parts = []
    for ex in examples:
        parts.append(f"""### Example: {ex.get('id', 'unknown')}
Category: {ex.get('method_category', '')}
Intent: {ex.get('intent', '')}
Available variables used: {', '.join(ex.get('available_variables_used', []))}

Before:
```python
{ex.get('before_snippet', '')}
```

After:
```python
{ex.get('after_snippet', '')}
```

Diff:
```
{ex.get('diff', '')}
```

Why semantic: {ex.get('why_semantic', '')}
Forbidden cosmetic: {ex.get('forbidden_cosmetic', '')}
Required changed terms: {', '.join(ex.get('required_changed_terms', []))}
""")
    return "\n".join(parts)


def _load_few_shots_fallback(path) -> str:
    """Fallback few-shot loading without PyYAML."""
    try:
        text = path.read_text(encoding="utf-8")
        return f"(Few-shot examples loaded as raw text)\n{text[:2000]}"
    except Exception:
        return "(No few-shot examples available)"

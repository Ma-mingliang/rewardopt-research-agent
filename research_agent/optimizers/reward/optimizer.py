"""Reward optimizer: propose reward function modifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.optimizers.base import BaseOptimizer, Candidate

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

This is fix attempt {attempt}/10. Generate a corrected diff that fixes the syntax error.
CRITICAL: The new lines MUST use the SAME indentation as the target context shown above.
The diff MUST use exact line numbers from the original code shown above.

Return JSON: {{"description": "<what you changed>", "diff": "<corrected unified diff>", "rationale": "<why>"}}"""


class RewardOptimizer(BaseOptimizer):
    """Optimizer for reward function modifications."""

    name = "reward"

    def propose_candidate(
        self,
        phase: dict,
        baseline_metrics: dict[str, dict[str, float]],
        ideas: list[dict] | None = None,
    ) -> Candidate:
        """Propose a reward function modification.

        Uses LLM to generate a patch based on allowed_changes and baseline metrics.
        Falls back to a no-op patch if LLM is unavailable.
        """
        from research_agent.optimizers.base import normalize_allowed_changes
        allowed = normalize_allowed_changes(phase.get("allowed_changes", []))
        forbidden = phase.get("forbidden_changes", [])

        # Read current reward function code
        code = self._read_reward_code(allowed)

        # Format baseline for prompt
        baseline_str = self._format_baseline(baseline_metrics)

        # Format ideas
        ideas_str = self._format_ideas(ideas or [])

        candidate_id = self.next_candidate_id()

        # Build source metadata from ideas
        source_meta = self._build_source_meta(ideas or [])

        # Skip LLM if mock mode
        if self._mock_llm:
            return Candidate(
                candidate_id=candidate_id,
                optimizer=self.name,
                description="No-op candidate (mock-llm mode)",
                patch_diff="",
                allowed_changes=allowed,
                source_idea=json.dumps(source_meta),
            )

        # Try LLM proposal with auto-fix loop (no limit on fix attempts)
        if self.llm_client is not None:
            max_fix_attempts = 30  # Safety limit to prevent infinite loops
            current_diff = None

            for attempt in range(max_fix_attempts + 1):
                try:
                    if attempt == 0:
                        # Initial proposal
                        response = self.llm_client.call(
                            system_prompt=PROPOSE_SYSTEM_PROMPT,
                            user_prompt=PROPOSE_USER_PROMPT.format(
                                file=allowed[0].get("file", "unknown") if allowed else "unknown",
                                code=code,
                                baseline=baseline_str,
                                allowed=allowed,
                                forbidden=forbidden,
                                ideas=ideas_str,
                            ),
                            max_tokens=4096,
                        )
                    else:
                        # Before LLM fix, try auto-indentation correction
                        if "indentation" in last_error.lower() or "indent" in last_error.lower():
                            auto_fixed = self._auto_fix_indentation(current_diff, allowed)
                            if auto_fixed:
                                auto_validation = self._validate_patch(auto_fixed, allowed)
                                if auto_validation["ok"]:
                                    print(f"[LLM] Auto-indentation fix succeeded (attempt {attempt})", flush=True)
                                    return Candidate(
                                        candidate_id=candidate_id,
                                        optimizer=self.name,
                                        description=f"{current_desc} (auto-indent fix) (rationale: {current_rationale})",
                                        patch_diff=auto_fixed,
                                        allowed_changes=allowed,
                                        source_idea=json.dumps(source_meta),
                                    )

                        # Fix attempt: send error back to LLM with target context
                        error_line = self._parse_error_line(last_error)
                        target_context = self._extract_target_context(error_line, allowed) if error_line else "(could not parse error line)"

                        fix_prompt = FIX_PROMPT.format(
                            code=code,
                            diff=current_diff,
                            error=last_error,
                            target_context=target_context,
                            attempt=attempt,
                        )
                        response = self.llm_client.call(
                            system_prompt=FIX_SYSTEM_PROMPT,
                            user_prompt=fix_prompt,
                            max_tokens=4096,
                        )

                    if response.parsed:
                        desc = response.parsed.get("description", "LLM-proposed change")
                        diff = response.parsed.get("diff", "")
                        rationale = response.parsed.get("rationale", "")

                        # Empty patch retry: ask LLM more explicitly for a diff
                        empty_diff_retries = 0
                        while not diff and empty_diff_retries < 30:
                            empty_diff_retries += 1
                            print(f"[LLM] Empty diff returned, retry {empty_diff_retries}/30 with explicit prompt", flush=True)
                            retry_prompt = (
                                f"You returned an empty diff. You MUST return a non-empty unified diff.\n\n"
                                f"Current reward code:\n```python\n{code}\n```\n\n"
                                f"Baseline metrics: {baseline_str}\n\n"
                                f"Ideas to implement:\n{ideas_str}\n\n"
                                f"Allowed changes: {json.dumps(allowed, indent=2)}\n\n"
                                f"Return a unified diff that modifies the reward function. "
                                f"The diff must start with @@ and contain actual code changes (+ and - lines).\n\n"
                                f"Return JSON: {{\"description\": \"...\", \"diff\": \"unified diff here\", \"rationale\": \"...\"}}"
                            )
                            retry_response = self.llm_client.call(
                                system_prompt=PROPOSE_SYSTEM_PROMPT,
                                user_prompt=retry_prompt,
                                max_tokens=4096,
                            )
                            if retry_response.parsed:
                                diff = retry_response.parsed.get("diff", "")
                                if diff:
                                    desc = retry_response.parsed.get("description", desc)
                                    rationale = retry_response.parsed.get("rationale", rationale)
                                    break

                        if diff:
                            # Add header if missing
                            if not diff.startswith("---"):
                                file_name = allowed[0].get("file", "env.py") if allowed else "env.py"
                                diff = f"--- a/{file_name}\n+++ b/{file_name}\n{diff}"

                            # Fix line counts in @@ header
                            diff = self._fix_diff_line_counts(diff)

                            # Validate: try to apply patch and check compilation
                            validation = self._validate_patch(diff, allowed)
                            if validation["ok"]:
                                return Candidate(
                                    candidate_id=candidate_id,
                                    optimizer=self.name,
                                    description=f"{desc} (rationale: {rationale})",
                                    patch_diff=diff,
                                    allowed_changes=allowed,
                                    source_idea=json.dumps(source_meta),
                                )
                            else:
                                # Patch failed validation, try to fix
                                current_diff = diff
                                current_desc = desc
                                current_rationale = rationale
                                last_error = validation["error"]
                                error_line = self._parse_error_line(last_error)
                                context_hint = f" (line {error_line})" if error_line else ""
                                print(f"[LLM] Patch validation failed (attempt {attempt}/{max_fix_attempts}){context_hint}: {last_error[:150]}", flush=True)
                                continue

                except Exception as e:
                    last_error = str(e)
                    print(f"[LLM] Exception (attempt {attempt}/{max_fix_attempts}): {last_error[:100]}", flush=True)
                    continue

            # All attempts failed, return no-op
            print(f"[LLM] All {max_fix_attempts} fix attempts failed", flush=True)

        # Fallback: no-op candidate (identity patch)
        return Candidate(
            candidate_id=candidate_id,
            optimizer=self.name,
            description="No-op candidate (LLM unavailable)",
            patch_diff="",
            allowed_changes=allowed,
            source_idea=json.dumps(source_meta),
        )

    def _read_reward_code(self, allowed_changes: list[dict]) -> str:
        """Read the current reward function code using AST parsing for precise extraction."""
        from research_agent.core.reward_extractor import extract_reward_function

        for change in allowed_changes:
            if isinstance(change, str):
                file_path = change
            elif isinstance(change, dict):
                file_path = change.get("file", "")
            else:
                continue

            if file_path:
                full_path = self.project_path / file_path
                if full_path.exists():
                    result = extract_reward_function(full_path, "__calculate_reward")
                    if result:
                        return result["code"]
                    # Fallback: try other reward-related functions
                    from research_agent.core.reward_extractor import extract_all_reward_functions
                    all_funcs = extract_all_reward_functions(full_path)
                    if all_funcs:
                        # Return the longest one (likely the main reward function)
                        best = max(all_funcs, key=lambda f: f["end_line"] - f["start_line"])
                        return best["code"]
                    # Last resort: show first 200 lines
                    try:
                        content = full_path.read_text(encoding="utf-8")
                        lines = content.splitlines()[:200]
                        return "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(lines))
                    except OSError:
                        continue
        return "# No reward function file found"

    def _fix_diff_line_counts(self, diff: str) -> str:
        """Fix line counts in @@ headers to match actual diff content."""
        import re

        lines = diff.split("\n")
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("@@"):
                # Parse the header
                match = re.match(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", line)
                if match:
                    old_start = match.group(1)
                    new_start = match.group(3)

                    # Count actual lines
                    old_count = 0
                    new_count = 0
                    j = i + 1
                    while j < len(lines):
                        l = lines[j]
                        if l.startswith("@@") or l.startswith("---") or l.startswith("+++"):
                            break
                        if l.startswith("-"):
                            old_count += 1
                        elif l.startswith("+"):
                            new_count += 1
                        elif l.startswith(" ") or l == "":
                            old_count += 1
                            new_count += 1
                        j += 1

                    # Fix the header
                    result.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@")
                    i += 1
                    continue
            result.append(line)
            i += 1

        return "\n".join(result)

    def _extract_target_context(self, error_line: int, allowed_changes: list[dict], context_radius: int = 10) -> str:
        """Extract code context around the error line with exact indentation."""
        if not allowed_changes:
            return "(no allowed changes specified)"
        file_name = allowed_changes[0].get("file", "env.py") if allowed_changes else "env.py"
        if isinstance(allowed_changes[0], str):
            file_name = allowed_changes[0]
        file_path = self.project_path / file_name

        if not file_path.exists():
            return "(file not found)"

        try:
            content = file_path.read_text(encoding="utf-8-sig")
            lines = content.splitlines()
            start = max(0, error_line - context_radius - 1)
            end = min(len(lines), error_line + context_radius)
            context_lines = []
            for i in range(start, end):
                marker = " >>> " if i == error_line - 1 else "     "
                context_lines.append(f"{i+1:4d}{marker}{lines[i]}")
            return "\n".join(context_lines)
        except Exception:
            return "(could not read file)"

    def _parse_error_line(self, error: str) -> int | None:
        """Extract line number from SyntaxError message."""
        import re
        match = re.search(r'line (\d+)', error)
        if match:
            return int(match.group(1))
        return None

    def _auto_fix_indentation(self, diff: str, allowed_changes: list[dict]) -> str | None:
        """Try to automatically fix indentation issues in a diff.

        Returns fixed diff if successful, None if cannot fix.
        """
        import re

        # Parse the diff to find added lines (+ lines)
        lines = diff.split("\n")
        added_lines = []
        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append(line[1:])  # Remove the +

        if not added_lines:
            return None

        # Get the target file to check expected indentation
        file_name = allowed_changes[0].get("file", "env.py") if allowed_changes else "env.py"
        if isinstance(allowed_changes[0], str):
            file_name = allowed_changes[0]
        file_path = self.project_path / file_name

        if not file_path.exists():
            return None

        try:
            original = file_path.read_text(encoding="utf-8-sig")
            original_lines = original.splitlines()
        except Exception:
            return None

        # Find the @@ header to get the target line range
        header_match = re.search(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', diff)
        if not header_match:
            return None

        target_start = int(header_match.group(1)) - 1  # 0-indexed

        # Check if added lines have inconsistent indentation with surrounding code
        if target_start >= len(original_lines):
            return None

        # Get the indentation of the line before the target
        ref_line_idx = target_start
        while ref_line_idx >= 0 and original_lines[ref_line_idx].strip() == "":
            ref_line_idx -= 1

        if ref_line_idx < 0:
            return None

        ref_indent = len(original_lines[ref_line_idx]) - len(original_lines[ref_line_idx].lstrip())

        # Check if all added lines have the same indentation
        added_indents = []
        for line in added_lines:
            if line.strip():  # Skip empty lines
                added_indents.append(len(line) - len(line.lstrip()))

        if not added_indents:
            return None

        # If added lines have inconsistent indentation, try to fix
        min_indent = min(added_indents)
        max_indent = max(added_indents)

        # If there's a significant indentation inconsistency (> 4 spaces difference)
        if max_indent - min_indent > 4:
            # Use the reference indentation
            fixed_lines = []
            for line in added_lines:
                if line.strip():
                    # Preserve relative indentation within the block
                    current_indent = len(line) - len(line.lstrip())
                    relative_indent = current_indent - min_indent
                    new_indent = ref_indent + relative_indent
                    fixed_lines.append(" " * new_indent + line.lstrip())
                else:
                    fixed_lines.append("")

            # Reconstruct the diff
            result = []
            added_idx = 0
            for line in lines:
                if line.startswith("+") and not line.startswith("+++"):
                    if added_idx < len(fixed_lines):
                        result.append("+" + fixed_lines[added_idx])
                        added_idx += 1
                else:
                    result.append(line)

            return "\n".join(result)

        return None

    def _validate_patch(self, diff: str, allowed_changes: list[dict]) -> dict:
        """Validate a patch by trying to apply it and checking compilation.

        Returns:
            {"ok": True} if patch applies and compiles,
            {"ok": False, "error": "..."} if it fails.
        """
        import tempfile
        import subprocess

        # Get the target file
        file_name = allowed_changes[0].get("file", "env.py") if allowed_changes else "env.py"
        if isinstance(allowed_changes[0], str):
            file_name = allowed_changes[0]
        file_path = self.project_path / file_name

        if not file_path.exists():
            return {"ok": False, "error": f"File not found: {file_path}"}

        # Read original content (handle BOM)
        original = file_path.read_text(encoding="utf-8-sig")

        # Try to apply patch using PatchManager's direct replacement
        try:
            from research_agent.core.patch_manager import PatchManager
            from research_agent.optimizers.base import Candidate

            # Create a temporary candidate
            temp_candidate = Candidate(
                candidate_id="validation_temp",
                optimizer=self.name,
                description="validation",
                patch_diff=diff,
                allowed_changes=allowed_changes,
            )

            pm = PatchManager(self.project_path, self.work_dir)
            result = pm._apply_direct_replacement(temp_candidate)

            if not result:
                return {"ok": False, "error": "Patch could not be applied (line numbers mismatch)"}

            # Read modified content (handle BOM)
            modified_content = file_path.read_text(encoding="utf-8-sig")

            # Check compilation (strip BOM if present)
            compile_content = modified_content.lstrip('﻿')
            try:
                compile(compile_content, str(file_path), "exec")
            except SyntaxError as e:
                # Restore original
                file_path.write_text(original, encoding="utf-8-sig")
                return {"ok": False, "error": f"SyntaxError: {e}"}

            # Check if the patch actually changed the reward function
            if modified_content == original:
                file_path.write_text(original, encoding="utf-8-sig")
                return {"ok": False, "error": "Patch did not change any code (no-op)"}

            # Verify the reward function still exists
            import ast
            try:
                tree = ast.parse(compile_content)
                has_reward = any(
                    isinstance(node, ast.FunctionDef) and node.name == "__calculate_reward"
                    for node in ast.walk(tree)
                )
                if not has_reward:
                    file_path.write_text(original, encoding="utf-8-sig")
                    return {"ok": False, "error": "Patch removed __calculate_reward function"}
            except SyntaxError:
                pass

            # Restore original (validation only, don't keep changes)
            file_path.write_text(original, encoding="utf-8-sig")
            return {"ok": True}

        except Exception as e:
            # Restore original
            file_path.write_text(original, encoding="utf-8-sig")
            return {"ok": False, "error": str(e)}

    def _generate_diff(self, allowed_changes: list[dict], new_code: str) -> str:
        """Generate a unified diff by replacing the function body."""
        import re

        if not new_code:
            return ""

        for change in allowed_changes:
            if isinstance(change, str):
                file_path = change
            elif isinstance(change, dict):
                file_path = change.get("file", "")
            else:
                continue
            if not file_path:
                continue
            full_path = self.project_path / file_path
            if not full_path.exists():
                continue

            try:
                content = full_path.read_text(encoding="utf-8")
                line_range = change.get("line_range")
                if not line_range or len(line_range) != 2:
                    continue

                start, end = line_range
                old_lines = content.splitlines()
                symbol = change.get("symbol", "")

                # Find the actual function start line
                func_start = start
                for i in range(max(0, start-1), min(end, len(old_lines))):
                    if symbol and f"def {symbol}" in old_lines[i]:
                        func_start = i + 1  # 1-indexed
                        break

                # Get function body (the lines to replace)
                old_func = old_lines[func_start-1:end]
                if not old_func:
                    continue

                # Use new_code as-is (LLM should generate correct indentation)
                new_lines = new_code.splitlines()

                # Build the diff manually
                old_count = len(old_func)
                new_count = len(new_lines)

                diff_lines = [
                    f"--- a/{file_path}",
                    f"+++ b/{file_path}",
                    f"@@ -{func_start},{old_count} +{func_start},{new_count} @@",
                ]

                # Add removed lines
                for line in old_func:
                    diff_lines.append(f"-{line}")

                # Add added lines
                for line in new_lines:
                    diff_lines.append(f"+{line}")

                return "\n".join(diff_lines)
            except OSError:
                continue

        return ""

    def _format_baseline(self, metrics: dict[str, dict[str, float]]) -> str:
        lines = []
        for name, vals in metrics.items():
            mean = vals.get("mean", 0)
            std = vals.get("std", 0)
            lines.append(f"  {name}: {mean:.4f} (std: {std:.4f})")
        return "\n".join(lines) if lines else "  (no baseline metrics)"

    def _format_ideas(self, ideas: list[dict]) -> str:
        if not ideas:
            return "  (no ideas available)"
        lines = []
        for idea in ideas[:5]:
            cat = idea.get("category", "")
            desc = idea.get("description", "")
            # Rich method from pool
            if idea.get("implementation_template"):
                core = idea.get("core_idea", desc)
                formula = idea.get("reward_formula", "N/A")
                template = idea.get("implementation_template", "N/A")
                layers = ", ".join(idea.get("applicable_layers", []))
                metrics = ", ".join(idea.get("applicable_metrics", []))
                risks = ", ".join(idea.get("risks", [])[:2])
                lines.append(f"  [{cat}] {core}")
                lines.append(f"    Formula: {formula}")
                lines.append(f"    Template: {template}")
                if layers:
                    lines.append(f"    Layers: {layers}")
                if metrics:
                    lines.append(f"    Metrics: {metrics}")
                if risks:
                    lines.append(f"    Risks: {risks}")
            else:
                lines.append(f"  - [{cat}] {desc}")
        return "\n".join(lines)

    @staticmethod
    def _build_source_meta(ideas: list[dict]) -> dict:
        """Extract source metadata from ideas for candidate tracking."""
        method_ids = []
        categories = []
        source_papers = []
        for idea in ideas:
            mid = idea.get("method_id", "")
            if mid:
                method_ids.append(mid)
            cat = idea.get("category", "")
            if cat and cat not in categories:
                categories.append(cat)
            papers = idea.get("source_papers", [])
            for p in papers:
                if p not in source_papers:
                    source_papers.append(p)
            # Also check source_paper dict
            sp = idea.get("source_paper", {})
            pid = sp.get("paper_id", "")
            if pid and pid not in source_papers:
                source_papers.append(pid)
        return {
            "source_method_ids": method_ids,
            "source_categories": categories,
            "source_papers": source_papers,
            "source_idea": "pool_methods" if method_ids else "extracted_ideas",
        }

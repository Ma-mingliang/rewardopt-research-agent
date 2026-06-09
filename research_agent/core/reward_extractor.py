"""Extract reward function code from Python files using AST parsing.

Provides precise extraction of the __calculate_reward function with
correct line numbers for LLM-based optimization.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def extract_reward_function(file_path: Path, function_name: str = "__calculate_reward") -> dict[str, Any] | None:
    """Extract a specific function from a Python file using AST.

    Args:
        file_path: Path to the Python file.
        function_name: Name of the function to extract (default: __calculate_reward).

    Returns:
        Dict with:
            - code: str (function code with line numbers)
            - start_line: int (1-indexed start line)
            - end_line: int (1-indexed end line, inclusive)
            - full_code: str (entire file content)
        Or None if function not found.
    """
    try:
        content = file_path.read_text(encoding="utf-8-sig")  # Handle BOM
    except OSError:
        return None

    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Try removing BOM if present
        if content.startswith('﻿'):
            content = content[1:]
            try:
                tree = ast.parse(content)
            except SyntaxError:
                return None
        else:
            return None

    lines = content.splitlines()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            start_line = node.lineno
            end_line = node.end_lineno if hasattr(node, 'end_lineno') else start_line

            # Include decorator if present
            if node.decorator_list:
                start_line = node.decorator_list[0].lineno

            # Include 3 lines of context before the function
            show_start = max(0, start_line - 4)
            show_end = min(len(lines), end_line + 1)

            # Number the lines
            numbered_lines = []
            for i in range(show_start, show_end):
                numbered_lines.append(f"{i+1:4d} | {lines[i]}")

            return {
                "code": "\n".join(numbered_lines),
                "start_line": start_line,
                "end_line": end_line,
                "full_code": content,
                "function_name": function_name,
            }

    return None


def extract_all_reward_functions(file_path: Path) -> list[dict[str, Any]]:
    """Extract all functions with 'reward' in their name from a Python file.

    Args:
        file_path: Path to the Python file.

    Returns:
        List of dicts, each with code, start_line, end_line, function_name.
    """
    try:
        content = file_path.read_text(encoding="utf-8-sig")  # Handle BOM
    except OSError:
        return []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        if content.startswith('﻿'):
            content = content[1:]
            try:
                tree = ast.parse(content)
            except SyntaxError:
                return []
        else:
            return []

    lines = content.splitlines()
    results = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and "reward" in node.name.lower():
            start_line = node.lineno
            end_line = node.end_lineno if hasattr(node, 'end_lineno') else start_line

            if node.decorator_list:
                start_line = node.decorator_list[0].lineno

            show_start = max(0, start_line - 2)
            show_end = min(len(lines), end_line + 1)

            numbered_lines = []
            for i in range(show_start, show_end):
                numbered_lines.append(f"{i+1:4d} | {lines[i]}")

            results.append({
                "code": "\n".join(numbered_lines),
                "start_line": start_line,
                "end_line": end_line,
                "function_name": node.name,
            })

    return results


def get_function_line_range(file_path: Path, function_name: str = "__calculate_reward") -> tuple[int, int] | None:
    """Get the line range of a function without extracting code.

    Args:
        file_path: Path to the Python file.
        function_name: Name of the function.

    Returns:
        (start_line, end_line) tuple (1-indexed), or None if not found.
    """
    try:
        content = file_path.read_text(encoding="utf-8-sig")  # Handle BOM
    except OSError:
        return None

    try:
        tree = ast.parse(content)
    except SyntaxError:
        if content.startswith('﻿'):
            try:
                tree = ast.parse(content[1:])
            except SyntaxError:
                return None
        else:
            return None

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            start = node.lineno
            end = node.end_lineno if hasattr(node, 'end_lineno') else start
            return (start, end)

    return None

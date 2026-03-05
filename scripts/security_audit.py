#!/usr/bin/env python3
"""Phase 0 Security Audit — static analysis for client-connector app/ directory.

Usage
-----
    python scripts/security_audit.py [--path app/]

Exit codes
----------
    0   No issues found
    1   One or more security issues detected (suitable for CI gate)

Checks performed
----------------
  [C1] Auth bypass pattern  — ``if.*debug.*not.*user`` or ``if not settings.debug``
                              conditionally skipping auth
  [C2] Weak JWT secret      — ``os.getenv("JWT_SECRET", "<non-empty-default>")``
  [C3] Auth in query params — ``Query(`` used in WebSocket/HTTP auth handlers
  [C4] gRPC insecure call   — ``grpc.insecure_channel(`` or ``grpc.aio.insecure_channel(``
  [C5] Subprocess unguarded — ``subprocess.Popen`` / ``subprocess.run`` without an
                              ``assert.*env.*local`` guard in the same function body
  [C6] Hardcoded secret     — string literals matching known-weak secret defaults
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator


# =============================================================================
# Data model
# =============================================================================


@dataclass
class Finding:
    check_id: str          # e.g. "C1"
    file: Path
    line: int
    code: str              # the offending source line (stripped)
    description: str       # human-readable description of the problem
    fix: str               # suggested fix

    def __str__(self) -> str:
        rel = self.file
        return (
            f"\n  [{self.check_id}] {rel}:{self.line}\n"
            f"       Code : {self.code}\n"
            f"       Issue: {self.description}\n"
            f"       Fix  : {self.fix}"
        )


# =============================================================================
# Checker utilities
# =============================================================================


def _source_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except SyntaxError:
        return None


def _line(lines: list[str], lineno: int) -> str:
    """Return the source line at 1-based lineno, stripped."""
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return "<unknown>"


# =============================================================================
# Check C1 — Auth bypass conditional on debug flag
# =============================================================================

_C1_PATTERNS = [
    # if not settings.debug and not user:
    re.compile(r"\bif\b.+\bdebug\b.+\bnot\b.+\buser\b", re.IGNORECASE),
    # if not settings.debug:  (standalone near auth)
    re.compile(r"\bif\b.+not.+settings\.debug", re.IGNORECASE),
    # if settings.debug or not user
    re.compile(r"\bif\b.+settings\.debug\b.+\bnot\b.+\buser\b", re.IGNORECASE),
    # conditional auth skip: any pattern where debug affects whether we check auth
    re.compile(r"\bif\b.*\bdebug\b.*\bauth\b", re.IGNORECASE),
]

_C1_FIX = (
    "Remove the debug condition entirely. Auth must always be enforced: "
    "`if not user: await ws.close(code=4001); return`"
)


def check_c1_auth_bypass(path: Path, lines: list[str]) -> Iterator[Finding]:
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pattern in _C1_PATTERNS:
            if pattern.search(stripped):
                yield Finding(
                    check_id="C1",
                    file=path,
                    line=lineno,
                    code=stripped,
                    description="Auth check conditionally skipped based on debug flag — "
                                "creates a security bypass that allows unauthenticated access",
                    fix=_C1_FIX,
                )
                break  # one finding per line


# =============================================================================
# Check C2 — os.getenv("JWT_SECRET", "<non-empty-default>")
# =============================================================================

_C2_GETENV = re.compile(
    r"""os\.getenv\s*\(\s*['"](?:JWT_SECRET|JWT_SECRET_KEY|SECRET_KEY)['"]\s*,\s*(['"])(.+?)\1\s*\)"""
)

_C2_FIX = (
    "Remove the default value: `os.environ['JWT_SECRET']` (raises KeyError on missing) "
    "or use Pydantic Field with no default and add a startup validator."
)


def check_c2_weak_jwt_getenv(path: Path, lines: list[str]) -> Iterator[Finding]:
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        m = _C2_GETENV.search(stripped)
        if m:
            default_val = m.group(2)
            if default_val:  # non-empty default is the problem
                yield Finding(
                    check_id="C2",
                    file=path,
                    line=lineno,
                    code=stripped,
                    description=f"JWT_SECRET has a hardcoded fallback default {default_val!r}. "
                                "If the env var is unset in production, the app silently uses a known secret.",
                    fix=_C2_FIX,
                )


# =============================================================================
# Check C3 — Query() used in auth handlers (WebSocket or HTTP)
# =============================================================================

_C3_QUERY = re.compile(r"\bQuery\s*\(")

_AUTH_PARAM_NAMES = re.compile(
    r"\b(?:key|token|api_key|jwt|auth|authorization|access_token)\b", re.IGNORECASE
)

_C3_FIX = (
    "Move the parameter to a header: use `Header(default=None, alias='X-API-Key')` "
    "for API keys, or `Header(default=None, alias='Authorization')` for JWT tokens. "
    "Reject requests that use legacy query params with 401."
)


def check_c3_auth_query_params(path: Path, lines: list[str]) -> Iterator[Finding]:
    # Only scan files that look like they handle auth
    content = "\n".join(lines)
    if not re.search(r"\b(?:WebSocket|APIRouter|@router\.|@app\.)\b", content):
        return

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if _C3_QUERY.search(stripped) and _AUTH_PARAM_NAMES.search(stripped):
            yield Finding(
                check_id="C3",
                file=path,
                line=lineno,
                code=stripped,
                description="Auth credential passed as a query parameter via Query(). "
                            "Query params appear in server logs, browser history, proxy logs, "
                            "and Referer headers — leaking credentials.",
                fix=_C3_FIX,
            )


# =============================================================================
# Check C4 — grpc.insecure_channel() (AST-based)
# =============================================================================

_C4_FIX = (
    "Replace with `create_grpc_channel(host)` from `app/grpc/channel.py`. "
    "That helper uses `grpc.aio.secure_channel()` with TLS credentials loaded "
    "from GRPC_CA_CERT_PATH (and optionally mTLS certs)."
)


def check_c4_grpc_insecure(path: Path, lines: list[str]) -> Iterator[Finding]:
    tree = _parse(path)
    if tree is None:
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func

        # grpc.insecure_channel(...)  OR  grpc.aio.insecure_channel(...)
        is_insecure = (
            isinstance(func, ast.Attribute)
            and func.attr == "insecure_channel"
        )
        if is_insecure:
            yield Finding(
                check_id="C4",
                file=path,
                line=node.lineno,
                code=_line(lines, node.lineno),
                description="grpc.insecure_channel() transmits data in plaintext. "
                            "All internal gRPC traffic must use TLS.",
                fix=_C4_FIX,
            )


# =============================================================================
# Check C5 — subprocess.Popen/run without ENV assertion guard (AST-based)
# =============================================================================

_SUBPROCESS_CALLS = {"Popen", "run", "call", "check_call", "check_output"}

_C5_FIX = (
    "Add `assert settings.env == 'local', f'Subprocess mode forbidden in ENV={settings.env}'` "
    "immediately before the subprocess call, and add the same check to `validate_secrets()` "
    "at startup so the app refuses to start with subprocess mode in non-local envs."
)


def _function_body_src(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Collect all source segment text from the function — approximated from the AST."""
    parts = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assert):
            # Check if this assert references 'env' and 'local'
            try:
                src = ast.unparse(node)
                parts.append(src)
            except Exception:
                pass
    return " ".join(parts)


def _has_env_assertion(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function body contains an assert that checks env == 'local'."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assert):
            try:
                src = ast.unparse(node.test)
            except Exception:
                src = ""
            if "env" in src.lower() and "local" in src.lower():
                return True
        # Also accept a raise inside an if-env check
        if isinstance(node, ast.If):
            try:
                cond = ast.unparse(node.test)
            except Exception:
                cond = ""
            if "env" in cond.lower() and "local" in cond.lower():
                return True
    return False


def check_c5_subprocess_unguarded(path: Path, lines: list[str]) -> Iterator[Finding]:
    tree = _parse(path)
    if tree is None:
        return

    # Collect all function definitions keyed by their line range
    funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node)

    def _enclosing_func(lineno: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        best = None
        for fn in funcs:
            end = getattr(fn, "end_lineno", fn.lineno + 999)
            if fn.lineno <= lineno <= end:
                if best is None or fn.lineno > best.lineno:
                    best = fn
        return best

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func

        # subprocess.Popen / subprocess.run / subprocess.call etc.
        is_sub = (
            isinstance(func, ast.Attribute)
            and func.attr in _SUBPROCESS_CALLS
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        )
        # os.system(...)
        is_os_system = (
            isinstance(func, ast.Attribute)
            and func.attr == "system"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        )

        if not (is_sub or is_os_system):
            continue

        # Check for shell=True
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                yield Finding(
                    check_id="C5",
                    file=path,
                    line=node.lineno,
                    code=_line(lines, node.lineno),
                    description="subprocess called with shell=True — enables shell injection "
                                "if any argument is derived from external input.",
                    fix="Convert to a list of arguments and remove shell=True: "
                        "`subprocess.Popen([executable, arg1, arg2], ...)` — no shell=True needed.",
                )

        # Check for missing ENV assertion in enclosing function
        enc = _enclosing_func(node.lineno)
        if enc is None or not _has_env_assertion(enc):
            yield Finding(
                check_id="C5",
                file=path,
                line=node.lineno,
                code=_line(lines, node.lineno),
                description="subprocess call not guarded by an ENV assertion. "
                            "This allows subprocess execution in staging/production environments.",
                fix=_C5_FIX,
            )


# =============================================================================
# Check C6 — Hardcoded weak secret strings
# =============================================================================

_WEAK_SECRETS = {
    "dev_secret_key",
    "changeme",
    "secret",
    "development",
    "test123",
    "password",
    "password123",
    "admin",
    "supersecret",
    "12345",
    "your-secret-here",
    "mysecret",
}

# Only flag when these appear to be secret/key values — look at context
_C6_SECRET_CONTEXT = re.compile(
    r"\b(?:SECRET|KEY|PASSWORD|TOKEN|JWT|AUTH|CRED)\b", re.IGNORECASE
)

_C6_FIX = (
    "Remove the hardcoded default. Load from environment only: `os.environ['VAR_NAME']`. "
    "Add a startup validator that rejects known-weak values. "
    "Generate strong secrets with: `python -c \"import secrets; print(secrets.token_hex(32))\"`"
)


_C6_SKIP_SUBSTRINGS = (
    "_BANNED", "_FORBIDDEN", "_REJECTED", "_DISALLOWED", "_WEAK",
    "BANNED_VALUES", "BANNED_SECRET",
    "validate_secrets", "validate_jwt", "validate_cc",
    "field_validator", "frozenset", "pytest.raises",
)


def _c6_is_guard_line(context: str) -> bool:
    """Return True if the context looks like a banned-values guard definition."""
    cl = context.lower()
    return any(s.lower() in cl for s in _C6_SKIP_SUBSTRINGS)


def check_c6_hardcoded_secrets(path: Path, lines: list[str]) -> Iterator[Finding]:
    tree = _parse(path)
    if tree is None:
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        val = node.value.strip().lower()
        if val not in _WEAK_SECRETS:
            continue
        if not (1 <= node.lineno <= len(lines)):
            continue

        source_line = lines[node.lineno - 1]
        # Also check the line before for multi-line assignments (e.g. frozenset spread across lines)
        prev_line = lines[node.lineno - 2] if node.lineno >= 2 else ""
        context_str = source_line + " " + prev_line

        # Only flag if the line looks like it's setting a secret/key variable
        if not _C6_SECRET_CONTEXT.search(context_str):
            continue

        # Skip lines that are clearly part of a banned-value guard/allowlist definition
        if _c6_is_guard_line(context_str):
            continue

        yield Finding(
            check_id="C6",
            file=path,
            line=node.lineno,
            code=source_line.strip(),
            description=f"Hardcoded weak secret default {node.value!r} found. "
                        "If the env var is not set, this value will be used silently in production.",
            fix=_C6_FIX,
        )


# =============================================================================
# Runner
# =============================================================================

_CHECKERS: list[tuple[str, Callable]] = [
    ("C1", check_c1_auth_bypass),
    ("C2", check_c2_weak_jwt_getenv),
    ("C3", check_c3_auth_query_params),
    ("C4", check_c4_grpc_insecure),
    ("C5", check_c5_subprocess_unguarded),
    ("C6", check_c6_hardcoded_secrets),
]

_CHECK_DESCRIPTIONS = {
    "C1": "Auth bypass conditional on debug flag",
    "C2": "os.getenv() with non-empty default for JWT_SECRET",
    "C3": "Auth credentials in query params (Query())",
    "C4": "grpc.insecure_channel() usage",
    "C5": "subprocess call without ENV=local assertion",
    "C6": "Hardcoded weak secret defaults",
}


def _should_skip(path: Path) -> bool:
    """Skip test files, migrations, and __pycache__."""
    parts = path.parts
    return any(
        p in ("__pycache__", ".git", "migrations", "alembic")
        or p.startswith("test_")
        or p.endswith("_test.py")
        for p in parts
    )


def audit(root: Path, enabled_checks: set[str] | None = None) -> list[Finding]:
    if enabled_checks is None:
        enabled_checks = {c for c, _ in _CHECKERS}

    all_findings: list[Finding] = []

    py_files = sorted(root.rglob("*.py"))
    if not py_files:
        print(f"  [warn] No Python files found under {root}", file=sys.stderr)

    for py_file in py_files:
        if _should_skip(py_file):
            continue
        try:
            lines = _source_lines(py_file)
        except OSError:
            continue

        for check_id, checker in _CHECKERS:
            if check_id not in enabled_checks:
                continue
            for finding in checker(py_file, lines):
                all_findings.append(finding)

    return all_findings


# =============================================================================
# Output formatting
# =============================================================================

_COLOURS = {
    "red": "\033[91m",
    "yellow": "\033[93m",
    "green": "\033[92m",
    "cyan": "\033[96m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}


def _c(colour: str, text: str) -> str:
    """Apply ANSI colour if stdout is a tty."""
    if sys.stdout.isatty():
        return f"{_COLOURS[colour]}{text}{_COLOURS['reset']}"
    return text


def _print_findings(findings: list[Finding], root: Path) -> None:
    # Group by check ID
    by_check: dict[str, list[Finding]] = {}
    for f in findings:
        by_check.setdefault(f.check_id, []).append(f)

    for check_id, group in sorted(by_check.items()):
        desc = _CHECK_DESCRIPTIONS.get(check_id, "")
        print(
            _c("bold", f"\n{'─' * 70}")
            + "\n"
            + _c("red", f"  [{check_id}] {desc}")
            + f"  ({len(group)} finding{'s' if len(group) != 1 else ''})"
        )
        for f in group:
            rel = f.file.relative_to(root.parent) if root.parent != root else f.file
            print(f"\n  {_c('cyan', str(rel))}:{_c('yellow', str(f.line))}")
            print(f"    {_c('bold', 'Code :')} {f.code}")
            print(f"    {_c('bold', 'Issue:')} {f.description}")
            print(f"    {_c('bold', 'Fix  :')} {f.fix}")

    print()


def _print_summary(findings: list[Finding], root: Path) -> None:
    by_check: dict[str, int] = {}
    for f in findings:
        by_check[f.check_id] = by_check.get(f.check_id, 0) + 1

    total = len(findings)
    print(_c("bold", f"\n{'═' * 70}"))
    print(_c("bold", "  Phase 0 Security Audit — Summary"))
    print(_c("bold", f"{'═' * 70}"))
    print(f"  Scanned : {root}")
    print(f"  Findings: {_c('red', str(total)) if total else _c('green', '0')}")
    print()

    for check_id, count in sorted(by_check.items()):
        desc = _CHECK_DESCRIPTIONS.get(check_id, "")
        print(f"  [{check_id}] {count:>3}  {desc}")

    if not findings:
        print(_c("green", "  ✓ No Phase 0 security issues found.\n"))
    else:
        print(
            _c("red", f"\n  ✗ {total} issue{'s' if total != 1 else ''} found.")
            + "  Fix all issues before merging.\n"
        )


# =============================================================================
# CLI entrypoint
# =============================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="security_audit.py",
        description="Phase 0 security static analysis for ConFuse services.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("app"),
        help="Root directory to scan (default: app/)",
    )
    parser.add_argument(
        "--checks",
        nargs="*",
        choices=["C1", "C2", "C3", "C4", "C5", "C6"],
        default=None,
        metavar="CHECK",
        help="Restrict to specific check IDs, e.g. --checks C4 C5 (default: all)",
    )
    parser.add_argument(
        "--no-colour",
        action="store_true",
        help="Disable ANSI colour output (e.g. for plain CI logs)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit findings as JSON (one object per line) instead of human-readable",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Disable colour when requested or not a tty
    if args.no_colour:
        _COLOURS.update({k: "" for k in _COLOURS})

    root = args.path.resolve()
    if not root.exists():
        print(f"ERROR: Path not found: {root}", file=sys.stderr)
        return 2

    print(f"\n  Scanning {root} for Phase 0 security issues…\n")

    enabled = set(args.checks) if args.checks else None
    findings = audit(root, enabled_checks=enabled)

    if args.json_output:
        import json
        for f in findings:
            print(json.dumps({
                "check": f.check_id,
                "file": str(f.file),
                "line": f.line,
                "code": f.code,
                "description": f.description,
                "fix": f.fix,
            }))
    else:
        if findings:
            _print_findings(findings, root)
        _print_summary(findings, root)

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

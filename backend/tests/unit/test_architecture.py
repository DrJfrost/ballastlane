"""Executable enforcement of the dependency rule.

Clean Architecture is a claim about which module may import which. A diagram
in a README cannot enforce it and a code review will eventually miss one
import. These tests parse the actual import statements, so the boundary
breaks the build rather than eroding over six months.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "taskflow"

#: Outward dependencies each layer is allowed to have. The domain has none.
ALLOWED_LAYER_IMPORTS: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "application": frozenset({"domain"}),
    "infrastructure": frozenset({"domain", "application"}),
    "presentation": frozenset({"domain", "application", "infrastructure"}),
}

#: Third-party packages that must never appear in the inner layers. A single
#: ``from pydantic import BaseModel`` in an entity is how a domain model
#: quietly becomes a serialisation format.
FORBIDDEN_THIRD_PARTY = {
    "domain": frozenset(
        {
            "fastapi",
            "starlette",
            "sqlalchemy",
            "pydantic",
            "pydantic_settings",
            "celery",
            "redis",
            "jwt",
            "bcrypt",
            "slowapi",
            "alembic",
            "httpx",
        }
    ),
    "application": frozenset(
        {
            "fastapi",
            "starlette",
            "sqlalchemy",
            "pydantic",
            "pydantic_settings",
            "celery",
            "redis",
            "jwt",
            "bcrypt",
            "slowapi",
            "alembic",
            "httpx",
        }
    ),
}


def _python_files(layer: str) -> list[pathlib.Path]:
    return sorted((SRC / layer).rglob("*.py"))


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _layer_of(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == "taskflow" and parts[1] in ALLOWED_LAYER_IMPORTS:
        return parts[1]
    return None


@pytest.mark.unit
@pytest.mark.parametrize("layer", sorted(ALLOWED_LAYER_IMPORTS))
def test_layer_only_imports_inwards(layer: str) -> None:
    allowed = ALLOWED_LAYER_IMPORTS[layer] | {layer}
    violations: list[str] = []

    for path in _python_files(layer):
        for module in _imported_modules(path):
            imported_layer = _layer_of(module)
            if imported_layer is not None and imported_layer not in allowed:
                violations.append(
                    f"{path.relative_to(SRC)} imports {module} "
                    f"({layer} -> {imported_layer} is not allowed)"
                )

    assert not violations, "Dependency rule violated:\n  " + "\n  ".join(violations)


@pytest.mark.unit
@pytest.mark.parametrize("layer", sorted(FORBIDDEN_THIRD_PARTY))
def test_inner_layers_are_framework_free(layer: str) -> None:
    forbidden = FORBIDDEN_THIRD_PARTY[layer]
    violations: list[str] = []

    for path in _python_files(layer):
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root in forbidden:
                violations.append(f"{path.relative_to(SRC)} imports {module}")

    assert not violations, (
        f"The {layer} layer must not depend on a framework:\n  " + "\n  ".join(violations)
    )


@pytest.mark.unit
def test_domain_has_no_imports_outside_stdlib_and_itself() -> None:
    """The strongest statement: the domain is plain Python.

    It should be possible to copy ``taskflow/domain`` into a different
    application and have it work with nothing installed.
    """
    stdlib_roots = {
        "__future__",
        "abc",
        "collections",
        "dataclasses",
        "datetime",
        "enum",
        "functools",
        "math",
        "re",
        "typing",
        "uuid",
    }
    violations: list[str] = []

    for path in _python_files("domain"):
        for module in _imported_modules(path):
            root = module.split(".")[0]
            if root not in stdlib_roots and root != "taskflow":
                violations.append(f"{path.relative_to(SRC)} imports {module}")

    assert not violations, "Domain must stay dependency-free:\n  " + "\n  ".join(violations)


@pytest.mark.unit
def test_only_the_presentation_layer_knows_about_http_status_codes() -> None:
    """Status codes are a transport concern.

    If ``status.HTTP_404_NOT_FOUND`` starts appearing in use cases, the
    application layer has stopped being reusable from a worker or a CLI.
    """
    offenders: list[str] = []
    for layer in ("domain", "application", "infrastructure"):
        for path in _python_files(layer):
            text = path.read_text(encoding="utf-8")
            if "HTTP_4" in text or "HTTP_5" in text or "status_code" in text:
                offenders.append(str(path.relative_to(SRC)))

    assert not offenders, (
        "HTTP concepts leaked out of the presentation layer:\n  " + "\n  ".join(offenders)
    )

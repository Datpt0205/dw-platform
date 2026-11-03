"""Verify that every workspace package only imports what it declares, and is registered.

Complements import-linter: import-linter enforces direction/boundaries between
known modules, this script enforces that no package "borrows" a third-party or
workspace dependency it has not declared in its own pyproject.

It also checks that every uv workspace member is named at every place a
distribution has to be (studio-skeleton R1). A package missing from
`root_packages` is a package import-linter never looks at, and nothing said so:
`dw_docgen` was a member, first-party to ruff and absent from import-linter
until this check went in (failure-modes #0).

Usage: uv run python scripts/verify_architecture.py [--root DIR]
Exit code 0 = clean, 1 = violations found.
"""

from __future__ import annotations

import argparse
import ast
import sys
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# The import-linter contract every domain layer belongs to (CLAUDE.md "Layer
# rules"). A `domain` package outside it may import a framework unseen.
DOMAIN_CONTRACT = "Domain layers never import frameworks or providers"

# Studio's contracts (ADR 0100 point 3; studio-skeleton R5.7): each direct
# sub-package of `dw_studio` must be covered by every one that names it.
STUDIO = "dw_studio"
STUDIO_ADAPTERS_CONTRACT = "Studio inner layers never import Studio adapters"
STUDIO_LANGGRAPH_CONTRACT = "LangGraph only in Studio compilers"
STUDIO_CORE_CONTRACT = "Studio core imports no capability"
# The layers that may not import a Studio adapter (R5.4).
STUDIO_INNER_LAYERS = ("domain", "application", "workflows", "presentation")
# Not capabilities: the core they all build on, and the test support.
STUDIO_NON_CAPABILITIES = frozenset({"core", "testing"})

# The Python images that `uv sync` the workspace: each needs every member's
# manifest, or the lockfile resolves against a workspace that is not there.
PYTHON_DOCKERFILES = ("api.Dockerfile", "worker.Dockerfile", "docgen.Dockerfile")

# Import name -> distribution name for third-party packages we use.
IMPORT_TO_DIST = {
    "pydantic": "pydantic",
    "pydantic_settings": "pydantic-settings",
    "fastapi": "fastapi",
    "starlette": "fastapi",  # starlette ships with fastapi's dependency tree
    "uvicorn": "uvicorn",
    "sqlalchemy": "sqlalchemy",
    "alembic": "alembic",
    "asyncpg": "asyncpg",
    "langgraph": "langgraph",
    "qdrant_client": "qdrant-client",
    "redis": "redis",
    "httpx": "httpx",
    "websockets": "websockets",
    "minio": "minio",
    "boto3": "boto3",
    "opentelemetry": "opentelemetry-api",
    "prometheus_client": "prometheus-client",
    "langfuse": "langfuse",
    "jwt": "pyjwt",
    "yaml": "pyyaml",
    "jsonschema": "jsonschema",
    "referencing": "referencing",
    "deepagents": "deepagents",
    "playwright": "playwright",
    "reportlab": "reportlab",
    "langchain": "langchain",
    "langchain_core": "langchain-core",
    "langchain_openai": "langchain-openai",
    "dw_kernel": "dw-kernel",
    "dw_platform": "dw-platform",
    "dw_agent_runtime": "dw-agent-runtime",
    "dw_knowledge": "dw-knowledge",
    "dw_memory": "dw-memory",
    "dw_connectors": "dw-connectors",
    "dw_observability": "dw-observability",
    "dw_evals": "dw-evals",
    "dw_studio": "dw-studio",
    "dw_api": "dw-api",
    "dw_worker": "dw-worker",
    "dw_docgen": "dw-docgen",
}


def declared_dependencies(pyproject: Path) -> set[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps: set[str] = set()
    project = data.get("project", {})
    specs = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        specs.extend(group)
    for spec in specs:
        name = (
            spec.split("[")[0]
            .split(">")[0]
            .split("<")[0]
            .split("=")[0]
            .split("!")[0]
            .split(";")[0]
            .strip()
        )
        deps.add(name.lower())
    return deps


def imported_top_levels(src_dir: Path) -> dict[str, list[Path]]:
    imports: dict[str, list[Path]] = {}
    for py_file in src_dir.rglob("*.py"):
        # `testing` subpackages hold test-support helpers (e.g. the seed used by
        # every context's integration tests). Like the tests they serve, they
        # legitimately compose several bounded contexts and cannot declare those
        # as runtime dependencies without inverting the layering, so they are
        # exempt from the declared-dependency check.
        if "testing" in py_file.relative_to(src_dir).parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover — parse errors fail loudly
            print(f"SYNTAX ERROR in {py_file}: {exc}")
            sys.exit(1)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.setdefault(alias.name.split(".")[0], []).append(py_file)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.setdefault(node.module.split(".")[0], []).append(py_file)
    return imports


def check_package(package_dir: Path, root: Path = REPO_ROOT) -> list[str]:
    pyproject = package_dir / "pyproject.toml"
    src_dir = package_dir / "src"
    if not pyproject.exists() or not src_dir.exists():
        return []

    own_modules = {p.name for p in src_dir.iterdir() if p.is_dir()}
    declared = declared_dependencies(pyproject)
    violations: list[str] = []

    for module, files in sorted(imported_top_levels(src_dir).items()):
        if module in own_modules or module in sys.stdlib_module_names:
            continue
        dist = IMPORT_TO_DIST.get(module)
        if dist is None:
            violations.append(
                f"{package_dir.name}: unknown third-party import {module!r} "
                f"(add to IMPORT_TO_DIST) in {files[0].relative_to(root)}"
            )
        elif dist.lower() not in declared:
            violations.append(
                f"{package_dir.name}: imports {module!r} but does not declare "
                f"{dist!r} in {pyproject.relative_to(root)} "
                f"(first seen in {files[0].relative_to(root)})"
            )
    return violations


def _workspace_members(root: Path, config: dict[str, Any]) -> list[Path]:
    members: list[Path] = []
    for pattern in config["tool"]["uv"]["workspace"]["members"]:
        found = (p for p in root.glob(pattern) if (p / "pyproject.toml").is_file())
        members.extend(sorted(found))
    return members


def _import_name(member: Path) -> str | None:
    src = member / "src"
    if not src.is_dir():
        return None
    packages = sorted(p.name for p in src.iterdir() if (p / "__init__.py").is_file())
    return packages[0] if len(packages) == 1 else None


def _domain_packages(member: Path, import_name: str) -> list[str]:
    """Every `domain` package under the member's import package, at any depth (R1.2)."""
    base = member / "src"
    return sorted(
        ".".join(path.relative_to(base).parts)
        for path in (base / import_name).rglob("domain")
        if path.is_dir() and (path / "__init__.py").is_file()
    )


def _matches(pattern: str, module: str) -> bool:
    """Whether import-linter's module expression names `module` or an ancestor
    of it: `*` is one segment, `**` one or more (as 2.15 reads them)."""
    want, have = pattern.split("."), module.split(".")

    def walk(i: int, j: int) -> bool:
        if i == len(want):
            return True  # an ancestor of `module` is matched: it covers it
        if j == len(have):
            return False
        if want[i] == "**":
            return any(walk(i + 1, k) for k in range(j + 1, len(have) + 1))
        return (want[i] == "*" or want[i] == have[j]) and walk(i + 1, j + 1)

    return walk(0, 0)


def _covered(module: str, patterns: set[str]) -> bool:
    return any(_matches(pattern, module) for pattern in patterns)


def _contract(contracts: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next((c for c in contracts if c.get("name") == name), {})


def _studio_problems(root: Path, contracts: list[dict[str, Any]]) -> list[str]:
    """R5.7: every direct sub-package of `dw_studio` in each contract R5.2-R5.5
    asks of it, named with the contract it is missing from."""
    base = root / "packages" / "python" / "dw_studio" / "src" / STUDIO
    if not base.is_dir():
        return []
    subs = sorted(p.name for p in base.iterdir() if (p / "__init__.py").is_file())
    domain = _contract(contracts, DOMAIN_CONTRACT)
    adapters = _contract(contracts, STUDIO_ADAPTERS_CONTRACT)
    langgraph = _contract(contracts, STUDIO_LANGGRAPH_CONTRACT)
    core = _contract(contracts, STUDIO_CORE_CONTRACT)
    capabilities = [sub for sub in subs if sub not in STUDIO_NON_CAPABILITIES]
    independent = [
        set(c.get("modules", []))
        for c in contracts
        if c.get("type") == "independence"
        and any(
            _covered(f"{STUDIO}.x", {m}) or m.startswith(f"{STUDIO}.") for m in c.get("modules", [])
        )
    ]
    found: list[str] = []

    def need(sub: str, module: str, contract: str, field: str, patterns: set[str]) -> None:
        if not _covered(module, patterns):
            found.append(f"{STUDIO}.{sub}: {module} missing from the {field} of {contract!r}")

    for sub in subs:
        pkg = f"{STUDIO}.{sub}"
        need(
            sub,
            f"{pkg}.domain",
            DOMAIN_CONTRACT,
            "source_modules",
            set(domain.get("source_modules", [])),
        )
        for layer in STUDIO_INNER_LAYERS:
            need(
                sub,
                f"{pkg}.{layer}",
                STUDIO_ADAPTERS_CONTRACT,
                "source_modules",
                set(adapters.get("source_modules", [])),
            )
        need(
            sub,
            f"{pkg}.adapters",
            STUDIO_ADAPTERS_CONTRACT,
            "forbidden_modules",
            set(adapters.get("forbidden_modules", [])),
        )
        need(
            sub,
            pkg,
            STUDIO_LANGGRAPH_CONTRACT,
            "source_modules",
            set(langgraph.get("source_modules", [])),
        )
        if sub in capabilities:
            need(
                sub,
                pkg,
                STUDIO_CORE_CONTRACT,
                "forbidden_modules",
                set(core.get("forbidden_modules", [])),
            )
            if len(capabilities) > 1 and not any(pkg in modules for modules in independent):
                found.append(
                    f"{pkg}: missing from an independence contract of the Studio capabilities"
                )
    return found


def check_registration(root: Path) -> list[str]:
    """Every workspace member at every place a distribution must be named (R1.1, R1.2)."""
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    tool = config["tool"]
    sources = set(tool["uv"].get("sources", {}))
    first_party = set(tool["ruff"]["lint"]["isort"]["known-first-party"])
    mypy_path = set(tool["mypy"]["mypy_path"])
    coverage = set(tool["coverage"]["run"]["source"])
    root_packages = set(tool["importlinter"]["root_packages"])
    contracts: list[dict[str, Any]] = tool["importlinter"].get("contracts", [])
    domain_sources = set(_contract(contracts, DOMAIN_CONTRACT).get("source_modules", []))
    dockerfiles = {
        name: (root / "infra" / "docker" / name).read_text(encoding="utf-8").splitlines()
        for name in PYTHON_DOCKERFILES
    }

    missing: list[str] = []
    for member in _workspace_members(root, config):
        manifest = tomllib.loads((member / "pyproject.toml").read_text(encoding="utf-8"))
        dist = manifest["project"]["name"]
        name = _import_name(member)
        where = member.relative_to(root).as_posix()
        if name is None:
            missing.append(f"{where}: no single import package under src/")
            continue
        places = {
            "[tool.uv.sources]": dist in sources,
            "ruff known-first-party": name in first_party,
            "mypy mypy_path": f"{where}/src" in mypy_path,
            "coverage source": f"{where}/src" in coverage,
            "import-linter root_packages": name in root_packages,
            "IMPORT_TO_DIST": IMPORT_TO_DIST.get(name) == dist,
        }
        if where.startswith("packages/python/"):
            line = f"COPY {where}/pyproject.toml {where}/pyproject.toml"
            for dockerfile, lines in dockerfiles.items():
                places[f"infra/docker/{dockerfile} COPY manifest"] = line in lines
        missing.extend(f"{name}: missing from {place}" for place, ok in places.items() if not ok)
        missing.extend(
            f"{module}: missing from the source_modules of {DOMAIN_CONTRACT!r}"
            for module in _domain_packages(member, name)
            if not _covered(module, domain_sources)
        )
    missing.extend(_studio_problems(root, contracts))
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Declared dependencies and registration.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="the tree to check")
    root = parser.parse_args(argv).root.resolve()

    package_dirs = sorted(
        [
            *(root / "packages" / "python").iterdir(),
            root / "apps" / "api",
            root / "apps" / "chat",
            root / "apps" / "docgen",
            root / "apps" / "worker",
        ]
    )
    all_violations: list[str] = []
    checked = 0
    for package_dir in package_dirs:
        if package_dir.is_dir():
            all_violations.extend(check_package(package_dir, root))
            checked += 1
    unregistered = check_registration(root)

    if all_violations:
        print(f"Declared-dependency check FAILED ({len(all_violations)} violations):")
        for violation in all_violations:
            print(f"  - {violation}")
    else:
        print(f"Declared-dependency check passed for {checked} packages.")
    if unregistered:
        print(f"Registration check FAILED ({len(unregistered)} missing):")
        for line in unregistered:
            print(f"  - {line}")
    else:
        print("Registration check passed for every workspace member.")
    return 1 if all_violations or unregistered else 0


if __name__ == "__main__":
    raise SystemExit(main())

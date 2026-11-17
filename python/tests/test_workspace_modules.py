from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.fixture
def workspace(tmp_path):
    for name in ("core", "app"):
        package = tmp_path / name / name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (tmp_path / name / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "0.1.0"\ndependencies = []\n'
        )
    (tmp_path / "core/core/internal.py").write_text("value = 1\n")
    (tmp_path / "core/core/__init__.py").write_text("from core.internal import value\n")
    return tmp_path


def configure(workspace, enabled, dependencies=True):
    depends_on = '["core"]' if dependencies else "[]"
    (workspace / "tach.toml").write_text(
        'source_roots = ["core", "app"]\n'
        f"workspace_modules = {str(enabled).lower()}\n"
        '[[modules]]\npath = "core"\ndepends_on = []\n'
        '[[modules]]\npath = "app"\n'
        f"depends_on = {depends_on}\n"
        '[[interfaces]]\nfrom = ["core"]\nexpose = ["value"]\n'
    )


def check(workspace, command="check"):
    return subprocess.run(
        [sys.executable, "-m", "tach", command],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("public", [False, True])
def test_workspace_interface(workspace, enabled, public):
    configure(workspace, enabled)
    module = "core" if public else "core.internal"
    (workspace / "app/app/__init__.py").write_text(f"from {module} import value\n")
    result = check(workspace)
    assert result.returncode == (1 if enabled and not public else 0), result.stderr
    if enabled and not public:
        assert "core.internal.value" in result.stderr


@pytest.mark.parametrize("enabled", [False, True])
def test_workspace_dependencies(workspace, enabled):
    configure(workspace, enabled, dependencies=False)
    (workspace / "app/app/__init__.py").write_text("from core import value\n")
    result = check(workspace)
    assert result.returncode == (1 if enabled else 0), result.stderr


@pytest.mark.parametrize("enabled", [False, True])
def test_workspace_external_dependencies_still_checked(workspace, enabled):
    configure(workspace, enabled)
    (workspace / "app/app/__init__.py").write_text("from core import value\n")
    result = check(workspace, "check-external")
    assert result.returncode == 1
    assert "not declared" in result.stderr


@pytest.mark.parametrize("enabled", [False, True])
def test_workspace_sync_discovers_dependencies(workspace, enabled):
    configure(workspace, enabled, dependencies=False)
    (workspace / "app/app/__init__.py").write_text("from core import value\n")
    result = check(workspace, "sync")
    assert result.returncode == 0, result.stderr
    from tach.parsing.config import parse_project_config

    config = parse_project_config(root=workspace)
    app = next(module for module in config.modules if module.path == "app")
    assert [dependency.path for dependency in app.depends_on] == (
        ["core"] if enabled else []
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_workspace_layers(workspace, enabled):
    configure(workspace, enabled, dependencies=False)
    config = workspace / "tach.toml"
    config.write_text(
        'layers = ["upper", "lower"]\n'
        + config.read_text()
        .replace('path = "core"', 'path = "core"\nlayer = "upper"')
        .replace('path = "app"', 'path = "app"\nlayer = "lower"')
    )
    (workspace / "app/app/__init__.py").write_text("from core import value\n")
    result = check(workspace)
    assert result.returncode == (1 if enabled else 0), result.stderr


def test_workspace_sync_exposes_cycles(workspace):
    configure(workspace, True, dependencies=False)
    (workspace / "app/app/__init__.py").write_text("from core import value\n")
    (workspace / "core/core/__init__.py").write_text("import app\nvalue = 1\n")
    result = check(workspace, "sync")
    assert result.returncode == 0, result.stderr
    config = workspace / "tach.toml"
    config.write_text("forbid_circular_dependencies = true\n" + config.read_text())
    result = check(workspace)
    assert result.returncode == 1
    assert "circular" in result.stderr.lower()


def test_workspace_third_party_import_not_internal(workspace):
    configure(workspace, True, dependencies=False)
    (workspace / "app/app/__init__.py").write_text("import requests\n")
    result = check(workspace)
    assert result.returncode == 0, result.stderr

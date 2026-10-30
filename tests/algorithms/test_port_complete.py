"""The algorithms cup-shake runs are complete: every local import resolves, except the arm-SDK
modules that were deliberately not ported, and the planner's call paths never reach them."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "algorithms"
LOCAL = ("cup_grasp_demo", "vision", "nero_revo2_control", "scripts")
# Direct arm-SDK owners: the framework drives the arm, so these were left out on purpose.
NOT_PORTED = {"cup_grasp_demo.flow.green_startup", "cup_grasp_demo.flow.batched_limits"}


def module_exists(name):
    path = ROOT.joinpath(*name.split("."))
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file() or path.is_dir()


def test_every_local_import_resolves():
    missing = []
    for source in sorted(ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                imported = [(alias.name, None) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported = [(node.module, alias.name) for alias in node.names]
            else:
                continue
            for module, name in imported:
                if module.split(".")[0] not in LOCAL or module in NOT_PORTED:
                    continue
                # `from package import name` may name a submodule; `from module import name` an attribute.
                package = ROOT.joinpath(*module.split(".")).is_dir()
                target = f"{module}.{name}" if name and package else module
                if target not in NOT_PORTED and not module_exists(target):
                    missing.append(f"{target} <- {source.relative_to(ROOT)}:{node.lineno}")
    assert not missing, missing


def test_planner_paths_never_reach_the_sdk_bridge():
    # cup_shake.legacy_green calls capture(), plan(), table() and held_geometry(), and replaces
    # snapshot() with framework feedback; nothing else on those paths may open an arm SDK client.
    source = (ROOT / "cup_grasp_demo/flow/green_pipeline.py").read_text()
    workflow = next(
        node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "Workflow"
    )
    methods = {node.name: node for node in workflow.body if isinstance(node, ast.FunctionDef)}
    seen, todo = set(), ["capture", "plan", "table", "held_geometry"]
    while todo:
        name = todo.pop()
        if name in seen or name not in methods or name == "snapshot":
            continue
        seen.add(name)
        todo += [
            node.func.attr
            for node in ast.walk(methods[name])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ]
    assert {"bridge", "prepare_step_runtime", "close_sdk"}.isdisjoint(seen), seen
    planner = (ROOT.parents[0] / "python/cup_shake/legacy_green.py").read_text()
    assert "work.snapshot = lambda" in planner


def test_vision_resources_import():
    import importlib
    import sys

    sys.path.insert(0, str(ROOT))
    runtime = importlib.import_module("cup_grasp_demo.flow.green_runtime")
    assert Path(runtime.__file__).resolve().is_relative_to(ROOT)
    assert hasattr(runtime, "VisionResources")

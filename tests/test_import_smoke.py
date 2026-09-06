import importlib
from pathlib import Path

def test_all_backend_modules_import():
    """
    FSC-C01: Every first-party module in app/ must import cleanly
    without unresolved annotations (e.g. NameError: name 'Optional' is not defined)
    or missing dependencies on all supported Python runtimes.
    """
    repo_root = Path(__file__).resolve().parent.parent
    app_root = repo_root / "app"
    discovered_modules = []

    for path in app_root.rglob("*.py"):
        rel_path = path.relative_to(repo_root)
        mod_name = ".".join(rel_path.with_suffix("").parts)
        discovered_modules.append(mod_name)

    assert len(discovered_modules) > 10, f"Should discover application modules, got {len(discovered_modules)}"

    failures = []
    for mod_name in sorted(discovered_modules):
        try:
            importlib.import_module(mod_name)
        except Exception as e:
            failures.append(f"{mod_name}: {type(e).__name__}: {e}")

    assert not failures, f"Failed to import modules:\n" + "\n".join(failures)


def test_api_handler_instantiation_smoke():
    """
    Smoke test instantiating ApiHandler to verify all imported service
    definitions are valid at runtime.
    """
    from app.backend.api.handler import ApiHandler
    handler = ApiHandler()
    assert handler is not None

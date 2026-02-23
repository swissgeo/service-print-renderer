import importlib
import inspect
import pkgutil

import pytest

import app.helpers


def _find_lru_cached_functions() -> list:
    """Discover all lru_cache-decorated functions in app.helpers submodules."""
    cached = []
    for module_info in pkgutil.walk_packages(app.helpers.__path__, app.helpers.__name__ + "."):
        module = importlib.import_module(module_info.name)
        for _name, obj in inspect.getmembers(module, inspect.isfunction):
            if hasattr(obj, "cache_clear"):
                cached.append(obj)
    return cached


_CACHED_FUNCTIONS = _find_lru_cached_functions()


@pytest.fixture(autouse=True)
def reset_lru_caches():
    """Clear all lru_cache singletons between tests to avoid cross-test pollution."""
    for func in _CACHED_FUNCTIONS:
        func.cache_clear()

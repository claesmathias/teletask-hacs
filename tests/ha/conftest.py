"""Make this repository's custom_components/teletask loadable by Home Assistant.

pytest-homeassistant-custom-component brings its own ``custom_components``
package (testing_config); add this repository's folder to its search path.
"""
from pathlib import Path

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

import custom_components  # noqa: E402

_REPO_COMPONENTS = str(Path(__file__).resolve().parents[2] / "custom_components")
if _REPO_COMPONENTS not in list(custom_components.__path__):
    custom_components.__path__.insert(0, _REPO_COMPONENTS)

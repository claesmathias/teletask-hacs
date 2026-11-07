"""Tests for loading, validating and saving config.json (no HA needed)."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "teletask_configfile", REPO / "custom_components" / "teletask" / "configfile.py"
)
configfile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(configfile)

ConfigFileError = configfile.ConfigFileError

VALID = {
    "type": "PICOS",
    "componentsTypes": {
        "RELAY": [{"number": 1, "description": "Garage", "hatype": "light"}],
        "LOCMOOD": [{"number": 5, "description": "Leaving house", "hatype": "scene"}],
    },
}


@pytest.fixture(autouse=True)
async def inter_test_cooldown():
    """Override the live-central cooldown from conftest; these tests are offline."""
    yield


def _code(exc_info) -> str:
    return exc_info.value.code


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------

@pytest.mark.parametrize("name", ["config.json", "config.json.backup"])
def test_repo_configs_are_valid(name):
    path = REPO / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    configfile.parse_config(path.read_text())


def test_valid_config_parses():
    assert configfile.parse_config(json.dumps(VALID)) == VALID


def test_invalid_json_reports_line_and_column():
    with pytest.raises(ConfigFileError) as exc:
        configfile.parse_config('{\n  "componentsTypes": {,}\n}')
    assert _code(exc) == "invalid_json"
    assert "line 2" in exc.value.detail and "column" in exc.value.detail


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ([], "top level"),
        ({"type": "PICOS"}, "componentsTypes"),
        ({"componentsTypes": {"LOCMOD": []}}, 'Unknown component type "LOCMOD"'),
        ({"componentsTypes": {"RELAY": {}}}, "must be a list"),
        ({"componentsTypes": {"RELAY": ["x"]}}, "must be an object"),
        ({"componentsTypes": {"RELAY": [{"description": "a"}]}}, '"number"'),
        ({"componentsTypes": {"RELAY": [{"number": "1"}]}}, '"number"'),
        ({"componentsTypes": {"RELAY": [{"number": True}]}}, '"number"'),
        ({"componentsTypes": {"RELAY": [{"number": 0}]}}, '"number"'),
        (
            {"componentsTypes": {"RELAY": [{"number": 3}, {"number": 3}]}},
            "RELAY number 3 appears more than once",
        ),
        (
            {"componentsTypes": {"RELAY": [{"number": 1, "description": 7}]}},
            '"description" must be text',
        ),
    ],
)
def test_structure_errors(data, fragment):
    with pytest.raises(ConfigFileError) as exc:
        configfile.validate_config(data)
    assert _code(exc) == "invalid_config"
    assert fragment in exc.value.detail


def test_same_number_in_different_types_is_allowed():
    configfile.validate_config(
        {"componentsTypes": {"RELAY": [{"number": 4}], "FLAG": [{"number": 4}]}}
    )


# ----------------------------------------------------------------------
# Path resolution
# ----------------------------------------------------------------------

def test_relative_path_resolves_inside_config_dir(tmp_path):
    target = tmp_path / "teletask" / "config.json"
    target.parent.mkdir()
    target.write_text("{}")
    assert configfile.resolve_config_path(" teletask/config.json ", str(tmp_path)) == str(
        target.resolve()
    )


def test_absolute_path_inside_config_dir(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("{}")
    assert configfile.resolve_config_path(str(target), str(tmp_path)) == str(target.resolve())


def test_missing_file(tmp_path):
    with pytest.raises(ConfigFileError) as exc:
        configfile.resolve_config_path("nope.json", str(tmp_path))
    assert _code(exc) == "file_not_found"


def test_empty_path(tmp_path):
    with pytest.raises(ConfigFileError) as exc:
        configfile.resolve_config_path("   ", str(tmp_path))
    assert _code(exc) == "file_not_found"


def test_parent_traversal_is_rejected(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (tmp_path / "secret.json").write_text("{}")
    with pytest.raises(ConfigFileError) as exc:
        configfile.resolve_config_path("../secret.json", str(config_dir))
    assert _code(exc) == "path_outside_config"


def test_sibling_dir_with_same_prefix_is_rejected(tmp_path):
    # "/x/config2" starts with "/x/config" as a string but is not inside it.
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    sibling = tmp_path / "config2"
    sibling.mkdir()
    (sibling / "c.json").write_text("{}")
    with pytest.raises(ConfigFileError) as exc:
        configfile.resolve_config_path(str(sibling / "c.json"), str(config_dir))
    assert _code(exc) == "path_outside_config"


def test_symlink_escaping_config_dir_is_rejected(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (config_dir / "link.json").symlink_to(outside)
    with pytest.raises(ConfigFileError) as exc:
        configfile.resolve_config_path("link.json", str(config_dir))
    assert _code(exc) == "path_outside_config"


# ----------------------------------------------------------------------
# Reading and writing
# ----------------------------------------------------------------------

def test_read_returns_text_and_data(tmp_path):
    path = tmp_path / "config.json"
    text = json.dumps(VALID, indent=2)
    path.write_text(text)
    assert configfile.read_config_file(str(path)) == (text, VALID)


def test_read_missing_file(tmp_path):
    with pytest.raises(ConfigFileError) as exc:
        configfile.read_config_file(str(tmp_path / "gone.json"))
    assert _code(exc) == "file_not_found"


def test_read_invalid_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{oops")
    with pytest.raises(ConfigFileError) as exc:
        configfile.read_config_file(str(path))
    assert _code(exc) == "invalid_json"


def test_write_preserves_text_and_keeps_backup(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("old\n")
    os.chmod(path, 0o640)
    new_text = '{\n  "componentsTypes": {   "RELAY": [] }\n}'

    configfile.write_config_file(str(path), new_text)

    assert path.read_text() == new_text + "\n"          # formatting kept, newline added
    assert (tmp_path / "config.json.bak").read_text() == "old\n"
    assert oct(path.stat().st_mode & 0o777) == oct(0o640)
    assert not list(tmp_path.glob(".teletask-*.tmp"))   # no temp files left behind


def test_write_new_file_has_no_backup(tmp_path):
    path = tmp_path / "config.json"
    configfile.write_config_file(str(path), "{}\n")
    assert path.read_text() == "{}\n"
    assert not (tmp_path / "config.json.bak").exists()


def test_write_to_missing_directory_reports_error(tmp_path):
    with pytest.raises(ConfigFileError) as exc:
        configfile.write_config_file(str(tmp_path / "missing" / "config.json"), "{}")
    assert _code(exc) == "cannot_write_file"


# ----------------------------------------------------------------------
# Structured editor helpers
# ----------------------------------------------------------------------

def test_editable_fields_per_type():
    assert configfile.editable_fields("RELAY") == ("number", "description", "hatype", "area", "pulse_ms")
    assert configfile.editable_fields("SENSOR") == (
        "number", "description", "area", "type", "decimals", "ha_unit_of_measurement",
    )
    assert configfile.editable_fields("INPUT") == ("number", "description", "area")
    assert set(configfile.TYPE_LABELS) == set(configfile.KNOWN_COMPONENT_TYPES)


def test_split_holds_back_unknown_keys_and_merge_restores_them():
    comps = [
        {"number": 2, "description": "Bedtime", "hatype": "scene", "type": "scene", "icon": "bed"},
        {"number": 1, "description": "All Off", "hatype": "scene"},
    ]
    items, extras = configfile.split_for_editor("GENMOOD", comps)
    assert items[0] == {"number": 2, "description": "Bedtime", "hatype": "scene"}
    assert extras == {2: {"type": "scene", "icon": "bed"}}
    merged = configfile.merge_from_editor(items, extras)
    assert [c["number"] for c in merged] == [1, 2]                      # sorted
    assert merged[1] == {"number": 2, "description": "Bedtime", "hatype": "scene", "type": "scene", "icon": "bed"}


def test_merge_cleans_editor_values():
    merged = configfile.merge_from_editor(
        [{"number": 16.0, "description": "Garage Door", "hatype": "button", "area": "", "pulse_ms": 500.0}],
        {},
    )
    assert merged == [{"number": 16, "description": "Garage Door", "hatype": "button", "pulse_ms": 500}]
    assert isinstance(merged[0]["number"], int) and isinstance(merged[0]["pulse_ms"], int)


def test_renumbered_component_does_not_inherit_old_extras():
    items, extras = configfile.split_for_editor("LOCMOOD", [{"number": 4, "description": "TV", "icon": "tv"}])
    items[0]["number"] = 9
    assert configfile.merge_from_editor(items, extras) == [{"number": 9, "description": "TV"}]


def test_decimals_shown_as_text():
    items, _ = configfile.split_for_editor("SENSOR", [{"number": 19, "description": "T", "decimals": 1}])
    assert items[0]["decimals"] == "1"


def test_merge_orders_keys():
    merged = configfile.merge_from_editor(
        [{"area": "Garage", "pulse_ms": 300, "description": "Door", "number": 16, "hatype": "button"}], {}
    )
    assert list(merged[0]) == ["number", "description", "hatype", "area", "pulse_ms"]


def test_format_config_round_trips_and_is_one_line_per_component():
    data = {
        "type": "PICOS",
        "componentsTypes": {
            "RELAY": [{"number": 1, "description": "Garage", "hatype": "light", "area": "Garage"}],
            "SENSOR": [{"number": 19, "description": "Température", "type": "TEMPERATURE", "ha_unit_of_measurement": "°C"}],
            "MOTOR": [],
        },
    }
    text = configfile.format_config(data)
    assert json.loads(text) == data
    assert '      { "number": 1, "description": "Garage", "hatype": "light", "area": "Garage" }' in text
    assert "Température" in text and "°C" in text                   # not \u-escaped
    assert '"MOTOR": []' in text


@pytest.mark.parametrize("name", ["config.json", "config.json.backup"])
def test_real_config_survives_editor_round_trip(name):
    path = REPO / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    original = configfile.parse_config(path.read_text())
    rebuilt = {k: v for k, v in original.items() if k != "componentsTypes"}
    rebuilt["componentsTypes"] = {}
    for type_name, comps in original["componentsTypes"].items():
        items, extras = configfile.split_for_editor(type_name, comps)
        rebuilt["componentsTypes"][type_name] = configfile.merge_from_editor(items, extras)
    reparsed = configfile.parse_config(configfile.format_config(rebuilt))
    # Same components with the same values (order within a type may be sorted).
    for type_name, comps in original["componentsTypes"].items():
        key = lambda c: c["number"]
        assert sorted(reparsed["componentsTypes"][type_name], key=key) == sorted(comps, key=key)
    assert {k: v for k, v in reparsed.items() if k != "componentsTypes"} == {
        k: v for k, v in original.items() if k != "componentsTypes"
    }

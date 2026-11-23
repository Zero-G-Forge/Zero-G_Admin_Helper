## =====================================================================
## TEST: tests/test_loadouts.py
## DESCRIPTION: Checks loadout templates on this PC: the three default names
## stay present, custom item packs can be saved and loaded, bad names and rows
## are rejected, and ADD TO TEMPLATE works on an existing custom pack. The
## real data/ folder is never touched. No Qt and no network.
## Run from the app root:  .venv/bin/python -m pytest tests/test_loadouts.py -q
## =====================================================================

# region Imports

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.shared import loadouts

# endregion


# region Fixtures

@pytest.fixture
def templates_file(tmp_path, monkeypatch):
    path = tmp_path / "loadout_templates.json"
    monkeypatch.setattr(loadouts, "TEMPLATES_FILE", str(path))
    return path

# endregion


# region Tests

def test_missing_file_still_has_the_three_defaults(templates_file):
    templates = loadouts.load_templates()
    assert list(templates)[:3] == loadouts.TEMPLATE_NAMES
    assert templates["STARTER"] == [] and templates["EXPLORER"] == [] and templates["BUILDER"] == []
    assert loadouts.list_template_names(templates) == loadouts.TEMPLATE_NAMES


def test_old_file_with_only_defaults_still_loads(templates_file):
    templates_file.write_text(json.dumps({
        "STARTER": [{"id": 1, "name": "Pistol", "count": 2}],
        "EXPLORER": [],
        "BUILDER": [{"id": 9, "name": "Wrench", "count": 0}, {"id": 8, "name": "Steel", "count": 10}],
    }))
    templates = loadouts.load_templates()
    assert templates["STARTER"] == [{"id": 1, "name": "Pistol", "count": 2}]
    assert templates["EXPLORER"] == []
    assert templates["BUILDER"] == [{"id": 8, "name": "Steel", "count": 10}]
    assert loadouts.list_template_names(templates) == loadouts.TEMPLATE_NAMES


def test_custom_pack_round_trip_and_name_rules(templates_file):
    rows = [{"id": 12, "name": "Medkit", "count": 5}, {"id": 13, "name": "Bandage", "count": 2}]
    assert loadouts.save_pack("  medkit pack ", rows) == rows
    templates = loadouts.load_templates()
    assert templates["MEDKIT PACK"] == rows
    assert loadouts.list_template_names(templates) == ["STARTER", "EXPLORER", "BUILDER", "MEDKIT PACK"]
    saved = json.loads(templates_file.read_text())
    assert "STARTER" in saved and "MEDKIT PACK" in saved
    loadouts.add_to_template("MEDKIT PACK", 12, "Medkit", 3)
    loadouts.add_to_template("MEDKIT PACK", 99, "Stim", 1)
    templates = loadouts.load_templates()
    assert templates["MEDKIT PACK"] == [
        {"id": 12, "name": "Medkit", "count": 8},
        {"id": 13, "name": "Bandage", "count": 2},
        {"id": 99, "name": "Stim", "count": 1},
    ]


@pytest.mark.parametrize("name", ["", "   ", "A" * 33, None, 12])
def test_bad_pack_names_are_rejected(templates_file, name):
    with pytest.raises(ValueError, match="bad pack name"):
        loadouts.normalize_pack_name(name)
    with pytest.raises(ValueError, match="bad pack name"):
        loadouts.save_pack(name, [{"id": 1, "name": "X", "count": 1}])
    assert loadouts.list_template_names() == loadouts.TEMPLATE_NAMES


def test_bad_rows_and_unknown_template_are_rejected(templates_file):
    with pytest.raises(ValueError, match="bad pack rows"):
        loadouts.save_pack("KIT", "not-a-list")
    with pytest.raises(ValueError, match="bad pack rows"):
        loadouts.save_pack("KIT", [{"id": "12", "name": "Medkit", "count": 5}])
    with pytest.raises(ValueError, match="bad pack rows"):
        loadouts.save_pack("KIT", [{"id": 12, "name": "Medkit", "count": 0}])
    with pytest.raises(ValueError, match="bad template, item or count"):
        loadouts.add_to_template("KIT", 1, "X", 1)
    loadouts.save_pack("KIT", [{"id": 1, "name": "X", "count": 1}])
    with pytest.raises(ValueError, match="bad template, item or count"):
        loadouts.add_to_template("KIT", 1, "X", 0)
    assert loadouts.load_templates()["KIT"] == [{"id": 1, "name": "X", "count": 1}]


def test_broken_file_and_invalid_custom_names_are_ignored(templates_file):
    templates_file.write_text("{not json")
    assert loadouts.load_templates()["STARTER"] == []
    templates_file.write_text(json.dumps({
        "STARTER": [{"id": 3, "name": "Ore", "count": 4}],
        "A" * 40: [{"id": 1, "name": "X", "count": 1}],
        "OK PACK": [{"id": 2, "name": "Y", "count": 1}],
        "BAD ROWS": "nope",
        "EMPTY": [],
    }))
    templates = loadouts.load_templates()
    assert templates["STARTER"] == [{"id": 3, "name": "Ore", "count": 4}]
    assert "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in templates
    assert "BAD ROWS" not in templates
    assert templates["OK PACK"] == [{"id": 2, "name": "Y", "count": 1}]
    assert templates["EMPTY"] == []
    assert loadouts.list_template_names(templates) == [
        "STARTER", "EXPLORER", "BUILDER", "EMPTY", "OK PACK",
    ]

# endregion

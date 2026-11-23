## =====================================================================
## TEST: tests/test_blueprint_library.py
## DESCRIPTION: Checks that blueprints are classified from the .epb type byte and the
## file name, and that load_blueprints reads Prefabs under a downloaded scenario folder
## (save copy first) or a stand-alone Prefabs folder. No Qt and no server.
## Run from the app root:  .venv/bin/python -m pytest tests/test_blueprint_library.py -q
## =====================================================================

# region Imports

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.library.blueprint_library import (classify_blueprint, load_blueprints,
                                                category_from_name, category_from_epb)

# endregion


# region Helpers

EPB_MAGIC = b"\x45\x52\x94\x78"


def write_epb(path, type_byte, extra=b""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = EPB_MAGIC + struct.pack("<I", 29) + struct.pack("<I", type_byte) + extra
    with open(path, "wb") as handle:
        handle.write(header)


def write_empty(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"")

# endregion


# region Classification

def test_type_byte_sets_sv_cv_hv_and_asteroid_poi(tmp_path):
    sv = tmp_path / "SV_Test.epb"
    cv = tmp_path / "GozantiFreighter.epb"
    hv = tmp_path / "Walker.epb"
    asteroid = tmp_path / "AsteroidIron.epb"
    write_epb(sv, 4)
    write_epb(cv, 8)
    write_epb(hv, 16)
    write_epb(asteroid, 1)
    assert classify_blueprint(sv.name, str(sv)) == "SV"
    assert classify_blueprint(cv.name, str(cv)) == "CV"
    assert classify_blueprint(hv.name, str(hv)) == "HV"
    assert classify_blueprint(asteroid.name, str(asteroid)) == "POI"


def test_type_2_uses_name_to_split_ba_and_poi(tmp_path):
    base = tmp_path / "BA_BurialChamber.epb"
    starter = tmp_path / "03. Base Starter (Empty).epb"
    statue = tmp_path / "ATL_Statue4.epb"
    poi = tmp_path / "CartellSpacestationPOI.epb"
    r2ba = tmp_path / "R2BA_TalonTowerStory.epb"
    baoj = tmp_path / "Eden_BAOJ_JunkT1_02.epb"
    bags = tmp_path / "BAgs_AshonLavaShelter.epb"
    for path in (base, starter, statue, poi, r2ba, baoj, bags):
        write_epb(path, 2)
    assert classify_blueprint(base.name, str(base)) == "BA"
    assert classify_blueprint(starter.name, str(starter)) == "BA"
    assert classify_blueprint(statue.name, str(statue)) == "POI"
    assert classify_blueprint(poi.name, str(poi)) == "POI"
    assert classify_blueprint(r2ba.name, str(r2ba)) == "BA"
    assert classify_blueprint(baoj.name, str(baoj)) == "BA"
    assert classify_blueprint(bags.name, str(bags)) == "BA"


def test_name_is_used_when_the_header_is_missing(tmp_path):
    named = tmp_path / "CV_Explorer.epb"
    unknown = tmp_path / "Greenhouse.epb"
    write_empty(named)
    write_empty(unknown)
    assert category_from_epb(str(named)) is None
    assert classify_blueprint(named.name, str(named)) == "CV"
    assert classify_blueprint(unknown.name, str(unknown)) == "POI"
    assert category_from_name("Eden_SVO_Beacon1.epb") == "SV"
    assert category_from_name("RBA_AbandonedDepot.epb") == "BA"

# endregion


# region Loading

def test_load_blueprints_save_wins_and_lists_each_name_once(tmp_path):
    folder = tmp_path / "Ascension-Reborn"
    write_epb(folder / "scenario" / "Prefabs" / "BA_Old.epb", 2)
    write_epb(folder / "save" / "Prefabs" / "BA_Old.epb", 2)
    write_epb(folder / "scenario" / "Prefabs" / "Prefab" / "Eden_SVO_Beacon1.epb", 4)
    write_epb(folder / "scenario" / "Prefabs" / "GozantiFreighter.epb", 8)
    write_empty(folder / "scenario" / "Prefabs" / "ATL_Statue4.epb")
    nearby = folder / "scenario" / "Prefabs" / "GozantiFreighter.png"
    os.makedirs(nearby.parent, exist_ok=True)
    nearby.write_bytes(b"\x89PNG\r\n\x1a\n")
    items = load_blueprints(str(folder))
    by_name = {item["name"]: item for item in items}
    assert set(by_name) == {"BA_Old", "Eden_SVO_Beacon1", "GozantiFreighter", "ATL_Statue4"}
    assert by_name["BA_Old"]["path"].endswith(os.path.join("save", "Prefabs", "BA_Old.epb"))
    assert by_name["Eden_SVO_Beacon1"]["filter_group"] == "SV"
    assert by_name["GozantiFreighter"]["filter_group"] == "CV"
    assert by_name["ATL_Statue4"]["filter_group"] == "POI"
    assert by_name["GozantiFreighter"]["image_path"].endswith("GozantiFreighter.png")


def test_load_blueprints_accepts_a_top_level_prefabs_folder(tmp_path):
    write_epb(tmp_path / "Prefabs" / "HV_Speeder.epb", 16)
    items = load_blueprints(str(tmp_path))
    assert len(items) == 1 and items[0]["filter_group"] == "HV"


def test_load_blueprints_empty_folder(tmp_path):
    assert load_blueprints(str(tmp_path)) == []
    assert load_blueprints(None) == []

# endregion

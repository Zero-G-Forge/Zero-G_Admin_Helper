## ==========================================
## ZERO-G ADMIN HELPER - BLUEPRINT LIBRARY DATA
## Builds the BLUEPRINTS list for the Library page from the downloaded server files:
##   <root>/Prefabs/**/*.epb
## Roots are the save copy first, then the scenario copy, under data/server_files/<scenario>/.
## A folder that already is a scenario root (it has Prefabs/ at the top) is also accepted,
## so tests and screenshots can use a small stand-alone copy.
## Read-only: nothing on disk or on a server is changed.
## Category comes from the .epb type byte (SV / CV / HV / asteroid POI) or, for bases
## (type 2) and files with no header, from the file name. Type-2 files named as a BA
## (or "Base") stay under BA; the rest of type 2, and names that include POI, are POI.
## ==========================================

# region Imports

import os
import re
import struct

# endregion


# region Constants

## Filter buttons on the BLUEPRINTS tab, in button order.
BLUEPRINT_FILTERS = ["BA", "CV", "SV", "HV", "POI"]

## Low byte of the uint32 at offset 8 in an Empyrion .epb (magic 0x45529478).
## Type 2 is a base-shaped blueprint; BA vs POI is decided from the file name.
EPB_MAGIC = b"\x45\x52\x94\x78"
FILE_TYPE_BY_BYTE = {
    1: "POI",
    2: "BA",
    4: "SV",
    8: "CV",
    16: "HV",
}

## Name tokens that map to a category, longest first. A leading R, R2, or RE2 is
## stripped before the match (RBA, R2BAO, RE2_CV, and so on).
NAME_TYPE_CODES = (
    ("POI", "POI"),
    ("BAOJ", "BA"),
    ("BAO", "BA"),
    ("BAJ", "BA"),
    ("BAW", "BA"),
    ("BAF", "BA"),
    ("BAGS", "BA"),
    ("BASM", "BA"),
    ("BA", "BA"),
    ("CVO", "CV"),
    ("CVJ", "CV"),
    ("CV", "CV"),
    ("SVO", "SV"),
    ("SVJ", "SV"),
    ("SV", "SV"),
    ("HVO", "HV"),
    ("HV", "HV"),
)

## Picture types accepted next to the .epb, or under SharedData/Content/Prefabs.
PREVIEW_TYPES = (".png", ".jpg", ".jpeg")

# endregion


# region Classification

def _tokens(stem):
    """Splits a file name (no extension) into tokens on punctuation and CamelCase."""
    parts = re.split(r"[^A-Za-z0-9]+", stem)
    tokens = []
    for part in parts:
        if not part:
            continue
        bits = re.findall(r"[A-Z]{2,}(?=[A-Z][a-z])|[A-Z]{2,}(?=[a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", part)
        if bits:
            tokens.extend(bits)
        else:
            tokens.append(part)
    return tokens


def _strip_r_prefix(token):
    """Removes a leading R, R2, or RE2 from a type token (RBA -> BA, R2BAO -> BAO)."""
    text = token.upper()
    for prefix in ("RE2", "R2", "R"):
        if text.startswith(prefix) and len(text) > len(prefix):
            return text[len(prefix):]
    return text


def category_from_name(file_name):
    """BA / CV / SV / HV / POI from the file name, or None when the name has no type token."""
    stem = os.path.splitext(os.path.basename(file_name))[0]
    upper = stem.upper()
    raw = [token.upper() for token in _tokens(stem)]
    stripped = [_strip_r_prefix(token) for token in raw]
    bag = raw + stripped
    if "POI" in bag or upper.endswith("POI") or "_POI" in upper or "POI_" in upper:
        return "POI"
    if "BASE" in bag:
        return "BA"
    for token in bag:
        for code, typ in NAME_TYPE_CODES:
            if token == code:
                return typ

            ## Longer codes may have a short suffix (BAOJ, BAgs, SVO...).
            if len(code) >= 3 and token.startswith(code):
                return typ
    return None


def category_from_epb(path):
    """SV / CV / HV / POI / BA from the .epb type byte, or None when the header cannot be read."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(12)
    except OSError:
        return None
    if len(header) < 12 or header[0:4] != EPB_MAGIC:
        return None
    type_byte = struct.unpack_from("<I", header, 8)[0] & 0xFF
    return FILE_TYPE_BY_BYTE.get(type_byte)


def classify_blueprint(file_name, path=None):
    """The filter group for one blueprint: file type when it is clear, else the name, else POI."""
    named = category_from_name(file_name)
    file_kind = category_from_epb(path) if path else None
    if file_kind in ("SV", "CV", "HV"):
        return file_kind
    if file_kind == "POI":
        return "POI"
    if file_kind == "BA":

        ## Type 2 is used for both player bases and world POIs. A BA (or Base) name
        ## stays under BA; a POI name, or no type token, goes under POI.
        if named == "BA":
            return "BA"
        return "POI"
    return named or "POI"

# endregion


# region Loading

def _prefab_roots(folder):
    """Prefab folders under the downloaded save and scenario, then a top-level Prefabs/ if present."""
    roots = []
    if not folder:
        return roots
    seen = set()
    for name in ("save", "scenario"):
        path = os.path.join(folder, name, "Prefabs")
        if os.path.isdir(path):
            full = os.path.abspath(path)
            if full not in seen:
                seen.add(full)
                roots.append(full)
    direct = os.path.join(folder, "Prefabs")
    if os.path.isdir(direct):
        full = os.path.abspath(direct)
        if full not in seen:
            seen.add(full)
            roots.append(full)
    return roots


def _preview_index(folder):
    """Lower-case stem -> picture path, from SharedData/Content/Prefabs in save then scenario."""
    index = {}
    if not folder:
        return index
    roots = []
    for name in ("save", "scenario"):
        path = os.path.join(folder, name, "SharedData", "Content", "Prefabs")
        if os.path.isdir(path):
            roots.append(path)
    direct = os.path.join(folder, "SharedData", "Content", "Prefabs")
    if os.path.isdir(direct):
        roots.append(direct)
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                stem, ext = os.path.splitext(filename)
                if ext.lower() not in PREVIEW_TYPES:
                    continue
                key = stem.lower()
                if key not in index:
                    index[key] = os.path.join(dirpath, filename)
    return index


def _preview_path(epb_path, stem, image_index):
    """A picture next to the .epb, or one with the same stem under SharedData/Content/Prefabs."""
    folder = os.path.dirname(epb_path)
    for ext in PREVIEW_TYPES:
        nearby = os.path.join(folder, stem + ext)
        if os.path.isfile(nearby):
            return nearby
    return image_index.get(stem.lower())


def load_blueprints(folder):
    """Returns blueprint dicts from Prefabs under folder, or [] when there are none."""
    roots = _prefab_roots(folder)
    if not roots:
        return []
    image_index = _preview_index(folder)
    found = []
    seen_names = set()
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if not filename.lower().endswith(".epb"):
                    continue
                key = filename.lower()
                if key in seen_names:
                    continue
                seen_names.add(key)
                path = os.path.join(dirpath, filename)
                stem = os.path.splitext(filename)[0]
                group = classify_blueprint(filename, path)
                found.append({
                    "name": stem,
                    "display_name": stem,
                    "id": stem,
                    "stack_size": "--",
                    "category": group,
                    "filter_group": group,
                    "image_path": _preview_path(path, stem, image_index),
                    "path": path,
                    "props": {},
                    "own_keys": None,
                })
    found.sort(key=lambda item: (item["display_name"].lower(), item["name"].lower()))
    return found

# endregion

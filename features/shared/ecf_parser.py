## ==========================================
## ZERO-G ADMIN HELPER - ECF PARSER
## Reads Empyrion .ecf text into plain Python dictionaries. Read-only: it never writes a file.
## An .ecf block looks like this:
##   { +Item Id: 200, Name: MagnesiumOre, Ref: OreTemplate
##     Mass: 6.51, type: float, display: true, formatter: Kilogram
##     { Child 0
##       Class: Ranged
##     }
##   }
## Each block becomes {"type": "Item", "header": {"Id": "200", ...}, "props": {...}, "children": [...]}.
## Each property becomes {"value": "6.51", "attrs": {"type": "float", "display": "true", "formatter": "Kilogram"}}.
## ==========================================

# region Imports

import csv
import re

# endregion


# region Constants

## '{ +Item Id: 2, Name: Flashlight' -> type 'Item', rest 'Id: 2, Name: Flashlight'
BLOCK_HEADER_PATTERN = re.compile(r"^\s*\{\s*[+-]?\s*([A-Za-z_]\w*)\s*(.*)$")

## Game colour and style tags inside text, e.g. [c][ff0000][b]READ FIRST[/b][-][/c] -> READ FIRST
STYLE_TAG_PATTERN = re.compile(r"\[/?[a-z]\]|\[[0-9a-fA-F]{6}\]|\[-\]")

# endregion


# region Line Helpers

def strip_comment(line_text):
    """Cuts off a # comment, but not a # inside "quotes"."""
    in_quotes = False
    for index, char in enumerate(line_text):
        if char == '"':
            in_quotes = not in_quotes
        elif char == "#" and not in_quotes:
            return line_text[:index]
    return line_text


def split_outside_quotes(text):
    """Splits on commas that are not inside "quotes"."""
    parts = []
    current = []
    in_quotes = False
    for char in text:
        if char == '"':
            in_quotes = not in_quotes
        if char == "," and not in_quotes:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts]


def parse_pairs(text):
    """'Id: 2, Name: Flashlight' -> {'Id': '2', 'Name': 'Flashlight'}. A part with no ':' joins the previous value."""
    pairs = {}
    last_key = None
    for part in split_outside_quotes(text):
        if ":" in part:
            key, value = part.split(":", 1)
            last_key = key.strip()
            pairs[last_key] = value.strip().strip('"')
        elif part and last_key is not None:
            pairs[last_key] += ", " + part.strip('"')
    return pairs


def parse_property(line_text):
    """'Mass: 6.51, type: float, display: true' -> ('Mass', {'value': '6.51', 'attrs': {...}}). None if not a property."""
    if ":" not in line_text:
        return None
    key, remainder = line_text.split(":", 1)
    key = key.strip()
    if not key:
        return None
    parts = split_outside_quotes(remainder)
    value_parts = [parts[0]]
    attrs = {}
    for part in parts[1:]:

        ## 'display: true' is an attribute; a part without ':' (e.g. 'Planet' in 'AllowAt: Space, Planet') is more value.
        if ":" in part:
            attr_key, attr_value = part.split(":", 1)
            attrs[attr_key.strip()] = attr_value.strip().strip('"')
        else:
            value_parts.append(part)
    value = ", ".join(value_part.strip().strip('"') for value_part in value_parts if value_part)
    return key, {"value": value, "attrs": attrs}

# endregion


# region Block Parsing

def parse_ecf_blocks(file_text):
    """Turns the whole .ecf text into a list of top-level blocks (children are nested inside)."""
    top_blocks = []
    open_blocks = []
    for raw_line in file_text.splitlines():
        line_text = strip_comment(raw_line).strip()
        if not line_text:
            continue

        ## New block: '{ +Item Id: 2, Name: Flashlight' or '{ Child 0'
        header_match = BLOCK_HEADER_PATTERN.match(line_text)
        if header_match:
            block_rest = header_match.group(2).strip()
            block = {
                "type": header_match.group(1),
                "header": parse_pairs(block_rest) if ":" in block_rest else {"Name": block_rest},
                "props": {},
                "children": [],
            }
            if open_blocks:
                open_blocks[-1]["children"].append(block)
            else:
                top_blocks.append(block)
            open_blocks.append(block)
            continue

        ## End of the innermost open block.
        if line_text.startswith("}"):
            if open_blocks:
                open_blocks.pop()
            continue

        ## A 'Key: value' line inside the innermost open block.
        if open_blocks:
            parsed = parse_property(line_text)
            if parsed:
                open_blocks[-1]["props"][parsed[0]] = parsed[1]
    return top_blocks


def resolve_refs(blocks):
    """Copies in what each block inherits through 'Ref: OtherName'. The block's own values win."""
    blocks_by_name = {block["header"].get("Name"): block for block in blocks if block["header"].get("Name")}
    resolved = []
    for block in blocks:
        merged_props = {}
        merged_children = list(block["children"])
        chain = []
        current = block

        ## Walk up the Ref chain (OreTemplate, Pistol...), stopping on a loop or a missing parent.
        while current is not None and id(current) not in chain:
            chain.append(id(current))
            for key, prop in current["props"].items():
                merged_props.setdefault(key, prop)
            if not merged_children and current["children"]:
                merged_children = list(current["children"])
            current = blocks_by_name.get(current["header"].get("Ref"))
        resolved_block = dict(block)
        resolved_block["props"] = merged_props
        resolved_block["children"] = merged_children

        ## Remember which lines were the block's own, so inherited values can be marked.
        resolved_block["own_keys"] = set(block["props"].keys())
        resolved.append(resolved_block)
    return resolved

# endregion


# region Text Files

def read_english_names(csv_path):
    """Reads a game text file (Localization.csv or PDA.csv) into {KEY: English text}. Empty if it can't be read."""
    english_names = {}
    try:

        ## newline="" lets the csv module handle line breaks inside quoted text.
        with open(csv_path, encoding="utf-8", errors="replace", newline="") as text_file:
            for row in csv.DictReader(text_file):
                english_text = STYLE_TAG_PATTERN.sub("", row.get("English") or "").strip()
                if row.get("KEY") and english_text:
                    english_names[row["KEY"]] = english_text
    except (OSError, csv.Error):
        pass
    return english_names

# endregion

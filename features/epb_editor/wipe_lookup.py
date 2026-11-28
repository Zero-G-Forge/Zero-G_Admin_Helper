## ==========================================
## ZERO-G ADMIN HELPER - WIPE LOOKUP
## Finds which playfields place a blueprint (prefab), so
## the wipe button only offers the playfields that matter.
## Read-only: it only reads the downloaded server files.
## ==========================================

# region Imports

import os
import re

# endregion


# region Constants

## A playfield file line like:  - GroupName: Zero_G_Hub2
## A commented line (# in front) never matches.
GROUP_LINE = re.compile(r"^\s*-\s*GroupName:\s*([^\s#]+)")

## A Sectors.yaml line like:
## - ['0,0,0', Akua Lo, Zero_Temperate, 'Human:1']
## Groups: the sector name, then the template folder name.
SECTOR_LINE = re.compile(r"^\s*-\s*\['[^']*',\s*(?:'([^']*)'|([^,]+?)),\s*([^,\]]+?),")

## The playfield files that place POIs.
PLAYFIELD_FILES = ("playfield_static.yaml", "playfield.yaml", "space_dynamic.yaml")

## A blueprint keeps its group name near the start.
HEADER_BYTES = 4096

# endregion


# region Group Names

## {group name: [playfield templates that place it]}
def read_group_users(scenario_folder):
    users = {}
    root = os.path.join(scenario_folder, "Playfields")
    if not os.path.isdir(root):
        return users
    for template in sorted(os.listdir(root)):
        for file_name in PLAYFIELD_FILES:
            path = os.path.join(root, template, file_name)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    found = GROUP_LINE.match(line)
                    if not found:
                        continue
                    group = found.group(1)
                    where = users.setdefault(group, [])
                    if template not in where:
                        where.append(template)
    return users

# endregion


# region Prefab Group

## The group name stored inside a blueprint, or None.
## It is the known group name found first in the header,
## written as one length byte and then the text.
def read_group_of_prefab(path, known_groups):
    try:
        with open(path, "rb") as handle:
            head = handle.read(HEADER_BYTES)
    except OSError:
        return None
    best = None
    for group in known_groups:
        marker = bytes([len(group)]) + group.encode("utf-8")
        spot = head.find(marker)
        if spot < 0:
            continue
        if best is None or spot < best[0]:
            best = (spot, group)
    if best is None:
        return None
    return best[1]

# endregion

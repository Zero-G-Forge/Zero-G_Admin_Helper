## Shared helpers for faction tags and club ranks (Owner / Admin / Member).
## Membership is always by factionId. The plys "faction" tag can be a leftover
## name from an older mapping, so the live Request_Get_Factions list is the
## source of the tag that is shown.

# region Role and Tag


## Empyrion IPlayer.FactionRole / PlayerInfo.factionRole uses Founder for the club owner.
ROLE_NAMES = {
    "founder": "Owner",
    "owner": "Owner",
    "admin": "Admin",
    "member": "Member",
    "guest": "Guest",
}


def format_faction_role(role):
    """Owner / Admin / Member / Guest, or '--' when the role is unknown."""
    text = str(role or "").strip()
    if not text or text == "--" or text.lower() == "none":
        return "--"
    return ROLE_NAMES.get(text.lower(), text)


def faction_id_number(value):
    """The faction id as an int, or None when it is missing or not a number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def faction_tag(factions, faction_id, fallback="--"):
    """The current [TAG] for a faction id from Request_Get_Factions, or fallback.

    Ids at or below 1 are the default human group, not a club, so the tag is '--'.
    """
    number = faction_id_number(faction_id)
    if number is None or number <= 1:
        return "--" if number is not None and number <= 1 else (fallback or "--")
    for row in factions or []:
        if not isinstance(row, dict):
            continue
        if faction_id_number(row.get("factionId")) == number:
            abbrev = str(row.get("abbrev") or "").strip()
            if not abbrev:
                return fallback or "--"
            if abbrev.startswith("["):
                return abbrev
            return "[" + abbrev + "]"
    return fallback or "--"


# endregion

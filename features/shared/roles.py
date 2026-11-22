# region Role Order
## Every role ZAH knows, lowest first. A role's position in this list is its rank.
## developer is Ray only; owner is the person whose server this is.
ROLE_ORDER = ("moderator", "admin", "owner", "developer")
# endregion


# region Role Checks
## Turns a role name into a rank number (moderator = 0 ... developer = 3).
## Anything unknown or missing gives -1, which is lower than every real role (fail closed).
def get_role_rank(role):
    role_name = str(role or "").strip().lower()
    if role_name in ROLE_ORDER:
        return ROLE_ORDER.index(role_name)
    return -1


## True only if the signed-in role is at least as high as the role needed.
## Example: has_role_at_least("owner", "admin") is True; has_role_at_least("admin", "owner") is False.
def has_role_at_least(user_role, needed_role):
    needed_rank = get_role_rank(needed_role)
    ## A typo in the needed role must never open the door, so an unknown needed role always says no.
    if needed_rank < 0:
        print(f"[ERROR] Roles: Unknown needed role '{needed_role}', access denied")
        return False
    return get_role_rank(user_role) >= needed_rank


## Server file uploads and LIVE MODE. Developers and owners always may; admins and moderators only when
## the owner granted Live file editing (live_flag must be exactly True). Anyone else, or an unknown role, may not.
def can_edit_live_files(user_role, live_flag=False):
    if has_role_at_least(user_role, "owner"):
        return True
    return get_role_rank(user_role) >= 0 and live_flag is True

# endregion
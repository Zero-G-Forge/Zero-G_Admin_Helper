# death_notice.py
# IronPython 3.4 — post a faction chat line when a player dies.

def on_player_died(player, event):
    cause = event.Cause or "unknown"
    msg = "{0} was lost ({1}) in {2}.".format(
        player.Name, cause, player.Playfield
    )
    if player.Faction:
        bridge.chat.send(to="faction", faction=player.Faction, message=msg)
    log.info(msg)

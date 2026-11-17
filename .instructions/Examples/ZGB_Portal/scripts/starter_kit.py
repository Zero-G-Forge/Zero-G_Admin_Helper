# starter_kit.py
# IronPython 3.4 — give a small kit the first time a player joins.
# This script is disabled in the mock until you turn it on and push live.

STARTER = [
    ("InterstellarCore", 1),
    ("OxygenBottle", 3),
    ("EmergencyRations", 5),
]


def on_player_joined(player, event):
    if player.Stats.Playtime != "0h":
        return
    for item_id, count in STARTER:
        bridge.items.give(player=player, item=item_id, count=count)
    bridge.chat.send(
        to=player,
        message="A starter kit was placed in your inventory. Fly safe.",
    )

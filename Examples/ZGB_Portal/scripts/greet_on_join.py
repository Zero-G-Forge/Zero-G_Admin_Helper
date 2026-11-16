# greet_on_join.py
# IronPython 3.4 — runs inside ZeroGBridge on the game thread.
# Greet a player when they join. The time limit stops a runaway script.

def on_player_joined(player, event):
    name = player.Name
    playfield = player.Playfield
    bridge.chat.send(
        to="global",
        message="Welcome to Zero-G Reborn, {0}! You are in {1}.".format(
            name, playfield
        ),
    )
    bridge.alerts.send(to=player, title="Welcome",
                       body="Type /help in chat if you need an admin.")
    log.info("Greeted {0} on join in {1}".format(name, playfield))

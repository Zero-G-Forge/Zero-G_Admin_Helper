## =====================================================================
## MODULE: features/bridge/command_pipe.py
## DESCRIPTION: Background thread (QThread) that owns the ZeroGBridge connection.
## Commands wait in a queue and go out one at a time, about 0.5 s apart,
## so the window stays responsive and the bridge is never flooded.
## =====================================================================

# region Imports

## queue.Queue is a thread-safe line: the window adds commands, the thread takes them.
import queue

## QThread runs code off the main window thread; pyqtSignal carries results back to it.
from PyQt6.QtCore import QThread, pyqtSignal

## The helpers built in Lesson 5 do the actual network work.
from features.bridge.bridge_connection import (
    close_bridge_socket,
    open_authenticated_socket,
    send_bridge_command,
)
from features.bridge.server_settings import get_active_profile

# endregion


# region Constants

## Pause between commands, per the bridge rules (about 500 ms).
INPUT_DELAY_SEC = 0.5

## How long the thread waits for a new command before checking whether it should stop.
QUEUE_CHECK_SEC = 0.25

# endregion


# region CommandPipe Class

class CommandPipe(QThread):
    ## Signals are messages from the thread back to the window.
    ## Widgets must only be changed on the window thread, so the thread never touches them directly.

    ## (server_name, is_connected): feeds MainCockpit.update_server_status.
    connection_changed = pyqtSignal(str, bool)

    ## (command, reply_text): one reply for each command sent.
    reply_received = pyqtSignal(str, str)

    ## (command): fired as each command leaves the queue (legacy signal name).
    command_dispatched = pyqtSignal(str)

    ## Fired when every queued command has been sent (legacy signal name).
    queue_empty = pyqtSignal()

    def __init__(self, input_delay_sec=INPUT_DELAY_SEC, parent=None):
        super().__init__(parent)
        self.input_delay_sec = input_delay_sec
        self.command_queue = queue.Queue()
        self.bridge_socket = None
        self.server_name = "OFFLINE"
        ## The thread keeps running while this is True; stop() flips it to False.
        self.is_running = False

    
    ## Adds one command to the queue. Safe to call from the window thread at any time.
    ## The thread sends it later, in order, after the 0.5 s pause.
    def enqueue_command(self, command_str):
        ## Input check: blank commands never enter the queue.
        command_str = str(command_str or "").strip()
        if not command_str:
            print("[ERROR] CommandPipe: Blank command ignored")
            return
        self.command_queue.put(command_str)
        ## Only the first word is logged, so values after the colon stay private.
        print(f"[INFO] CommandPipe: Queued command: {command_str.split(':')[0]}")

    ## Asks the thread to finish its current step and shut down cleanly.
    ## The connection itself is closed by the thread, in run(), on its way out.
    def stop(self):
        print("[INFO] CommandPipe: Stop requested")
        self.is_running = False
        ## wait() blocks until run() has fully finished (up to 3 s), so nothing is left half-open.
        self.wait(3000)

    
    ## The thread's main loop. Qt calls run() on the background thread after start().
    ## Everything network-related happens here, never on the window thread.
    def run(self):
        self.is_running = True
        try:
            ## Step 1: read the chosen server from data/server_config.json.
            server_profile = get_active_profile()
            if server_profile is None:
                self.connection_changed.emit("OFFLINE", False)
                return

            self.server_name = server_profile.get("server_name", "UNKNOWN")

            ## Step 2: connect and log in. The port is stored as text, so int() turns it into a number.
            self.bridge_socket = open_authenticated_socket(
                server_profile.get("input_ip", ""),
                int(server_profile.get("bridge_port", 30500)),
                server_profile.get("input_pass", ""),
            )
            if self.bridge_socket is None:
                self.connection_changed.emit(self.server_name, False)
                return

            ## The header dot turns green only after a real, successful login.
            self.connection_changed.emit(self.server_name, True)

            ## Step 3: send queued commands until stop() is called.
            while self.is_running:
                try:
                    ## get() waits up to QUEUE_CHECK_SEC for a command; queue.Empty means none arrived.
                    ## The short wait lets the loop notice stop() quickly.
                    command_str = self.command_queue.get(timeout=QUEUE_CHECK_SEC)
                except queue.Empty:
                    continue

                self.command_dispatched.emit(command_str)
                reply_text = send_bridge_command(self.bridge_socket, command_str)

                ## No reply counts as a lost connection for now: the dot goes red and the loop ends.
                ## Automatic reconnecting is a later lesson.
                ## (Nov 22, 2026: MainCockpit now reconnects after such a drop; see its Auto-Reconnect region.)
                if reply_text is None:
                    print("[WARNING] CommandPipe: No reply, treating connection as lost")
                    self.connection_changed.emit(self.server_name, False)
                    break

                self.reply_received.emit(command_str, reply_text)

                if self.command_queue.empty():
                    self.queue_empty.emit()

                ## The required pause between commands. msleep() is QThread's sleep, in milliseconds.
                self.msleep(int(self.input_delay_sec * 1000))

        except Exception as e:
            print(f"[ERROR] CommandPipe: Background loop failed: {e}")
            self.connection_changed.emit(self.server_name, False)

        ## "finally" always runs, even after return or an error, so the socket is always closed.
        finally:
            close_bridge_socket(self.bridge_socket)
            self.bridge_socket = None
            self.is_running = False
            print("[INFO] CommandPipe: Stopped")

# endregion
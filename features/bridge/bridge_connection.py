## =====================================================================
## MODULE: features/bridge/bridge_connection.py
## DESCRIPTION: Opens, logs in to, and closes the TCP connection to ZeroGBridge.
## Every network step has a timeout so a silent server can never freeze ZAH.
## =====================================================================

## region: Imports

## socket is Python's built-in "phone" for talking to another computer over the network.
## json reads the bridge's replies, which arrive as one line of JSON text each.
import json
import socket

## endregion


## region: Constants

## How many seconds to wait for the server before giving up (connect, login, replies).
BRIDGE_LOGIN_TIMEOUT = 5.0

## Every bridge command and reply is one line ending in these two characters
## (carriage return + new line), as the bridge rules require.
LINE_END = "\r\n"

## endregion


## region: Connection Helpers

## Hangs up a connection safely. Called after errors and on shutdown.
## Safe to call even if the socket is already closed or was never opened.
def close_bridge_socket(bridge_socket):
    if bridge_socket is None:
        return
    try:
        bridge_socket.close()
        print("[INFO] BridgeConnection: Socket closed")
    except Exception as e:
        print(f"[ERROR] BridgeConnection: Failed to close socket: {e}")


## Reads one reply line from the bridge and returns it as text (without the line end).
## Returns None if the server hangs up, stays silent past the timeout, or sends too much.
def read_bridge_line(bridge_socket, max_bytes=65536):
    try:
        ## Collected bytes go into this growing buffer until a new line arrives.
        received_bytes = b""
        while b"\n" not in received_bytes:
            ## recv() waits for up to 4096 bytes. The socket's timeout stops it
            ## from waiting forever.
            chunk = bridge_socket.recv(4096)

            ## An empty chunk means the server hung up the call.
            if not chunk:
                print("[WARNING] BridgeConnection: Server closed the connection")
                return None
            received_bytes += chunk

            ## Safety limit: a reply bigger than max_bytes is treated as broken.
            if len(received_bytes) > max_bytes:
                print(f"[ERROR] BridgeConnection: Reply over {max_bytes} bytes, dropped")
                return None

        ## Keep only the first line, turn the bytes into text, and trim the \r\n.
        first_line = received_bytes.split(b"\n", 1)[0]
        return first_line.decode("utf-8", errors="replace").strip()

    except socket.timeout:
        print(f"[WARNING] BridgeConnection: No reply within {bridge_socket.gettimeout()} s")
        return None
    except Exception as e:
        print(f"[ERROR] BridgeConnection: Failed to read reply: {e}")
        return None


## Dials the bridge and logs in with the token.
## Returns the open, logged-in socket, or None if anything fails.
def open_authenticated_socket(host, port, token, timeout=BRIDGE_LOGIN_TIMEOUT):
    ## Input checks: an address, a port, and a token are all required.
    if not host or not port or not token:
        print("[ERROR] BridgeConnection: Missing host, port or token, login skipped")
        return None

    bridge_socket = None
    try:
        print(f"[INFO] BridgeConnection: Connecting to {host}:{port}...")

        ## AF_INET + SOCK_STREAM means a normal internet (TCP) connection.
        bridge_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        bridge_socket.settimeout(timeout)
        bridge_socket.connect((str(host), int(port)))

        ## Send the login line. The token goes over the wire but is never printed.
        bridge_socket.sendall(f"auth:{token}{LINE_END}".encode("utf-8"))

        ## The bridge answers with one JSON line, e.g. {"type":"AUTH","status":"Authenticated"}.
        reply_line = read_bridge_line(bridge_socket)
        try:
            reply_data = json.loads(reply_line) if reply_line else {}
        except json.JSONDecodeError:
            reply_data = {}

        if reply_data.get("type") == "AUTH" and reply_data.get("status") == "Authenticated":
            print(f"[SUCCESS] BridgeConnection: Logged in to {host}:{port}")
            return bridge_socket

        ## Anything else counts as a failed login: hang up and report the status.
        print(f"[ERROR] BridgeConnection: Login refused on {host}:{port}, "
              f"status: {reply_data.get('status', 'no reply')}")
        close_bridge_socket(bridge_socket)
        return None

    except Exception as e:
        print(f"[ERROR] BridgeConnection: Could not connect to {host}:{port}: {e}")
        close_bridge_socket(bridge_socket)
        return None


## Sends one command line to a logged-in bridge and returns its one-line reply as text.
## Returns None if the command is blank, the socket is missing, or no reply arrives in time.
def send_bridge_command(bridge_socket, command_text):
    ## Input checks: a live socket and a non-blank command are both required.
    if bridge_socket is None:
        print("[ERROR] BridgeConnection: No connection, command not sent")
        return None
    command_text = str(command_text or "").strip()
    if not command_text:
        print("[ERROR] BridgeConnection: Blank command, nothing sent")
        return None

    try:
        ## Every command is one line ending in \r\n, as the bridge rules require.
        bridge_socket.sendall(f"{command_text}{LINE_END}".encode("utf-8"))

        ## Only the first word is logged, so any values after it stay out of the log.
        print(f"[INFO] BridgeConnection: Sent command: {command_text.split(':')[0]}")

        ## Wait for the single reply line (read_bridge_line handles the timeout).
        return read_bridge_line(bridge_socket)

    except Exception as e:
        print(f"[ERROR] BridgeConnection: Failed to send command: {e}")
        return None

## endregion
"""WebSocket message constants shared by the server and its clients.

See PROTOCOL.md for the full wire format and message-by-message behaviour.
"""

# client -> server
CLIENT_HELLO = "hello"
CLIENT_COMMAND = "command"
CLIENT_HOST = "host"

# server -> client
SERVER_STATE = "state"
SERVER_EVENT = "event"
SERVER_ERROR = "error"
SERVER_TAKEN_OVER = "taken-over"

# Engine event types whose payload carries private facts (curse assignments).
# They are never broadcast to any client.
PRIVATE_EVENT_TYPES = frozenset({"CurseViewed", "CurseDistributed"})

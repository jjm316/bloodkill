"""WebSocket message constants shared by the server and its clients.

See PROTOCOL.md for the full wire format and message-by-message behaviour.
"""

PROTOCOL_VERSION = "3"

# client -> server
CLIENT_HELLO = "hello"
CLIENT_COMMAND = "command"
CLIENT_HOST = "host"

# server -> client
SERVER_STATE = "state"
SERVER_EVENT = "event"
SERVER_ERROR = "error"
SERVER_ACK = "ack"
SERVER_TAKEN_OVER = "taken-over"

# Engine event types whose payload carries private facts. ADR 0014: curse
# ownership is public — CurseDistributed (recipients only) broadcasts, and the
# true/false split lives in the engine state, the saved command payloads and
# the inquisitor's projection, never in a public event. CurseViewed stays
# reserved.
PRIVATE_EVENT_TYPES = frozenset({"CurseViewed"})

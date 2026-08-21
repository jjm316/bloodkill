"""Pure Python domain engine for the Blood Bound compatible ruleset."""

from .engine import (
    Command,
    EngineState,
    Event,
    Player,
    RuleError,
    RulesEngine,
)
from .content import ContentBundle, ContentValidationError, load_content, validate_content
from .game_loop import Replay, run_deterministic_game
from .projection import legal_actions, project_state
from .persistence import (
    ReplayPlayer,
    ReplayStep,
    SAVE_SCHEMA_VERSION,
    SaveError,
    create_debug_link,
    create_save_document,
    dump_game,
    load_game,
    load_game_bytes,
    load_debug_link,
    load_save_document,
    migrate_save_document,
    migrate_save_file,
    save_game,
)

__all__ = [
    "Command", "ContentBundle", "ContentValidationError", "EngineState", "Event", "Player", "Replay",
    "ReplayPlayer", "ReplayStep", "RuleError", "RulesEngine", "SAVE_SCHEMA_VERSION", "SaveError",
    "create_debug_link", "create_save_document", "dump_game", "legal_actions", "load_content", "load_debug_link", "load_game", "load_game_bytes", "load_save_document",
    "migrate_save_document", "migrate_save_file", "project_state", "run_deterministic_game", "save_game", "validate_content",
]

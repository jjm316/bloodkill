"""Load and validate the bundled, original-placeholder content catalog."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


CONTENT_SCHEMA_VERSION = 1
_RESOURCE_IDS = {"quill", "shield", "sword", "staff", "fan"}
_FACTION_IDS = {"rose", "beast", "secret-order"}


class ContentValidationError(ValueError):
    """A content build error that identifies the invalid catalog field."""

    def __init__(self, code: str, **details: Any) -> None:
        self.code = code
        self.details = details
        super().__init__(f"{code}: {details}")


@dataclass(frozen=True)
class ContentBundle:
    catalog: Mapping[str, Any]
    translations: Mapping[str, Mapping[str, str]]
    licenses: Mapping[str, Mapping[str, str]]

    def text(self, locale: str, key: str, **arguments: object) -> str:
        """Resolve project-owned display text without exposing rule IDs to UI code."""
        try:
            template = self.translations[locale][key]
        except KeyError as error:
            raise ContentValidationError("content.translation-missing", locale=locale, key=key) from error
        return template.format(**arguments)


def load_content(content_dir: Path | None = None) -> ContentBundle:
    """Load the default catalog or a fixture directory, then fail fast on bad content."""
    directory = content_dir or Path(__file__).with_name("content")
    catalog = _read_json(directory / "catalog.json")
    licenses = _read_json(directory / "licenses.json")
    translations = {
        locale: _read_json(directory / "locales" / f"{locale}.json")
        for locale in catalog.get("supportedLocales", [])
    }
    bundle = ContentBundle(catalog=catalog, translations=translations, licenses=licenses)
    validate_content(bundle)
    return bundle


def validate_content(bundle: ContentBundle) -> None:
    """Validate IDs, references, localizations, and asset provenance at build time."""
    catalog = bundle.catalog
    if catalog.get("contentSchemaVersion") != CONTENT_SCHEMA_VERSION:
        raise ContentValidationError("content.schema-version", actual=catalog.get("contentSchemaVersion"))
    if catalog.get("rulesetId") != "blood-bound-compatible":
        raise ContentValidationError("content.ruleset-id", actual=catalog.get("rulesetId"))
    if not isinstance(catalog.get("contentVersion"), str) or not catalog["contentVersion"]:
        raise ContentValidationError("content.version-missing")

    supported_locales = _unique_strings(catalog.get("supportedLocales"), "content.locale-id")
    if catalog.get("defaultLocale") not in supported_locales:
        raise ContentValidationError("content.default-locale")
    if set(bundle.translations) != set(supported_locales):
        raise ContentValidationError("content.locale-file", expected=supported_locales, actual=sorted(bundle.translations))

    faction_ids = _unique_record_ids(catalog.get("factions"), "content.faction-id")
    if set(faction_ids) != _FACTION_IDS:
        raise ContentValidationError("content.factions", actual=sorted(faction_ids))
    resource_ids = _unique_record_ids(catalog.get("resources"), "content.resource-id")
    if set(resource_ids) != _RESOURCE_IDS:
        raise ContentValidationError("content.resources", actual=sorted(resource_ids))
    ability_ids = _unique_record_ids(catalog.get("abilities"), "content.ability-id")
    asset_ids = _unique_record_ids(catalog.get("assets"), "content.asset-id")
    unit_ids = _unique_record_ids(catalog.get("units"), "content.unit-id")

    for asset in catalog["assets"]:
        license_id = asset.get("licenseId")
        if license_id not in bundle.licenses:
            raise ContentValidationError("content.asset-license", assetId=asset["id"], licenseId=license_id)
    for ability in catalog["abilities"]:
        _validate_text_keys(bundle, ability, "ability")
    for faction in catalog["factions"]:
        _validate_text_keys(bundle, faction, "faction")
    for resource in catalog["resources"]:
        _validate_text_keys(bundle, resource, "resource")
    for unit in catalog["units"]:
        if unit.get("factionId") not in faction_ids:
            raise ContentValidationError("content.unit-faction", unitId=unit["id"])
        if unit.get("abilityId") not in ability_ids:
            raise ContentValidationError("content.unit-ability", unitId=unit["id"])
        if unit.get("assetId") not in asset_ids:
            raise ContentValidationError("content.unit-asset", unitId=unit["id"])
        if unit.get("factionId") == "secret-order":
            if unit.get("rank") != "fleur-cross":
                raise ContentValidationError("content.inquisitor-rank", unitId=unit["id"])
        elif not isinstance(unit.get("rank"), int) or not 1 <= unit["rank"] <= 9:
            raise ContentValidationError("content.unit-rank", unitId=unit["id"])
        _validate_text_keys(bundle, unit, "unit")

    expected_units = {f"unit.{faction}.{rank:02d}" for faction in ("rose", "beast") for rank in range(1, 10)}
    expected_units.add("unit.secret-order.inquisitor")
    if set(unit_ids) != expected_units:
        raise ContentValidationError("content.unit-deck", missing=sorted(expected_units - set(unit_ids)))

    board = catalog.get("board")
    if not isinstance(board, Mapping):
        raise ContentValidationError("content.board-missing")
    _unique_record_ids(board.get("zones"), "content.board-zone-id")
    for zone in board["zones"]:
        if zone.get("assetId") not in asset_ids:
            raise ContentValidationError("content.board-asset", zoneId=zone["id"])
        _validate_text_keys(bundle, zone, "board-zone")


def _validate_text_keys(bundle: ContentBundle, record: Mapping[str, Any], kind: str) -> None:
    for field in ("nameKey", "descriptionKey"):
        key = record.get(field)
        if not isinstance(key, str) or not key:
            raise ContentValidationError("content.text-key", kind=kind, field=field, recordId=record.get("id"))
        for locale, messages in bundle.translations.items():
            if key not in messages:
                raise ContentValidationError("content.translation-missing", locale=locale, key=key)


def _unique_strings(value: object, code: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ContentValidationError(code)
    if len(value) != len(set(value)):
        raise ContentValidationError("content.duplicate-id", ids=value)
    return value


def _unique_record_ids(value: object, code: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ContentValidationError(code)
    return _unique_strings([item.get("id") for item in value], code)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as source:
            value = json.load(source)
    except FileNotFoundError as error:
        raise ContentValidationError("content.file-missing", path=str(path)) from error
    except json.JSONDecodeError as error:
        raise ContentValidationError("content.invalid-json", path=str(path), line=error.lineno) from error
    if not isinstance(value, dict):
        raise ContentValidationError("content.invalid-root", path=str(path))
    return value

# Content catalog

`catalog.json` is the build-time, data-driven catalog for UI-facing identities, abilities, resources, board zones, and placeholder assets. Rule IDs (`unit.rose.01`), display keys (`unit.rose`), and asset IDs (`asset.token.placeholder`) are deliberately separate.

The catalog contains only project-original placeholder labels and CSS-rendered abstract asset references. It contains no copied artwork, logo, card wording, scans, or trade dress. Provenance is recorded in `licenses.json` for every asset reference.

`contentVersion` changes when content data changes. `contentSchemaVersion` changes only for incompatible catalog-shape changes. Readers reject unknown schema versions; new optional fields may be added to the current schema. A saved game keeps its engine `rulesetVersion`; content updates must not reinterpret its event log.

Run `python -m unittest discover -v` to validate the bundled catalog. `load_content()` accepts a fixture directory so a build or a test can reject missing locale keys, duplicate IDs, invalid references, incomplete decks, or assets without a license record before a client consumes them.

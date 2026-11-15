# Changelog

## Unreleased

### Changed

- **Plugin id renamed `haikei.wiki` → `herdr.wiki`** (owner decision,
  2026-11-15). Action names moved with the id (`herdr.wiki.search`,
  `herdr.wiki.capture`, `herdr.wiki.organize`, `herdr.wiki.context-dump`)
  and the plugin display name is now "Herdr Wiki". The `haikei_wiki`
  Python package, the `wiki` CLI and the launchd label
  (`com.haikei.wiki-organize`) are unchanged. The config dir herdr gives a
  plugin is named by its id, so existing installs move their `tbox.toml`
  once — see [README › Migrating from haikei.wiki](README.md#migrating-from-haikeiwiki).
  Until then the plugin keeps reading the legacy config file and prints a
  one-line migration hint to stderr; it never copies or deletes your files.

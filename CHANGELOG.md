# Changelog

## Unreleased

* `anki-cli tui`: a full-screen terminal app (optional extra `ankicli[tui]`, built on
  Textual). It has a deck tree, a reviewer with audio and undo, a browser with preview,
  an add/edit note form, statistics with a review heatmap and due forecast, sync with
  login and the full-sync choice, and profiles. It works on a local collection or against
  a server.
* The CLI no longer crashes on consoles with a legacy code page (Windows cp1252).

## 0.1.0 — 2026-10-26

First release.

* AnkiConnect legacy protocol: all 122 actions, with AnkiConnect's parameter coercion,
  result shapes and error strings (verified with AnkiConnect's own test suite).
* AnkiConnect API v1 (JSON-RPC 2.0): all 95 methods, schema-conformant results,
  cursors, state tokens, batches, notifications and operations.
* 61 extension methods: sync (login, normal and full sync, media), backups and
  `.colpkg` restore/export, deck tree, filtered decks, Custom Study, FSRS optimizer and
  simulator, card info, bury/reposition, CSV import/export, empty cards, media check,
  undo/redo, config, preferences, profiles, headless reviewer, browser and editors.
* Multiple collections per server (`/profiles/<name>/`), one worker thread each.
* CLI: serve, call, decks, deck, add, find, show, study, import, export, sync, stats,
  check, backup, profiles, info.
* HTTP/1.1 keep-alive with TCP_NODELAY; media over `GET /media/<file>` with ranges.
* Docker image, systemd unit, CI on Linux/macOS/Windows.

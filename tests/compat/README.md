# Anki-Connect compatibility suite

`run.py` executes Anki-Connect's own tests against anki-cli:

* the recorded client flows for **Yomitan**, **Obsidian_to_Anki**, **asbplayer**,
  **GameSentenceMiner**, **Jiten** and **LunaTranslator**;
* the legacy error baseline captured from the original implementation (every
  action's binding errors at versions 2, 4 and 6, plus native failure contracts);
* the legacy input-normalization rules;
* `test_v1_contract.py` (ours): every v1 method, with each result validated against
  Anki-Connect's published JSON schema, plus its catalogue of invalid inputs.

The upstream files are fetched at a pinned commit; `shim/` provides the `plugin`
interfaces they import, backed by a real anki-cli server over HTTP. They are run
separately from the main suite because they need network access and Anki-Connect's
source (GPL-3.0).

Excluded: cases that need Anki Desktop itself (its Qt reviewer/editor windows, the
permission dialog, a desktop with no profile loaded) or that exercise Anki-Connect's
in-process transport stubs. LunaTranslator's socket tests are replayed over a real
socket by `test_luna_socket.py`.

```bash
pip install -e ".[test]"
python tests/compat/run.py
```

Last result (Anki-Connect `62fc13d`, anki 26.09.3): 877 passed, 15 deselected.

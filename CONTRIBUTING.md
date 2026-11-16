# Contributing

Run Python 3.9+ with the standard library. No dependency installation is needed.

1. Start an isolated workspace: `python3 server.py --port 8766 --data-dir ./data/dev`.
2. Keep user data, keys, provider responses, logs, and downloaded vendor code out of commits.
3. Edit shared UI code in `static/app.js` and `static/discovery.js`. Update `locales/en.json`, run `python3 scripts/build_locales.py`, and commit generated English files too. Catalog replacements operate on application source, not rendered user text. Do not put executable code in translations.
4. Run `python3 -m unittest discover -s tests -v` and `python3 scripts/build_locales.py --check`. Use Node to syntax-check `static/*.js` and `static/en/*.js`.
5. Verify both languages in a browser. Check that existing Chinese workspaces can still be edited in English and that names, notes, source evidence, and unknown fees remain unchanged.

Provider tests must use synthetic responses unless someone explicitly supplies an account and authorizes credit usage. Do not make live searches part of CI. Never replace missing data with invented creators, audiences, fit scores, or quotes.

For changes to approval or price handling, include a regression test that verifies the user-visible outcome and spending/data boundary. Do not rely only on tests mirroring implementation details.

# Extella toolbar — auto-update

Single built bundle `toolbar.js` + `version.json` for the desktop app's auto-update.

**Raw URLs (main):**
- https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/version.json
- https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/toolbar.js

**Flow for the app:**
1. Poll `version.json`. If `version`/`sha` differ from the installed one → download `toolbar.js`.
2. Verify it contains the marker `Extella Plugins` and matches `bytes`.
3. Write to `<userData>/toolbar.js` and reload the toolbar view.

The app already injects `<userData>/toolbar.js` on load if present (else the bundled copy), so update = replace that file + reload.

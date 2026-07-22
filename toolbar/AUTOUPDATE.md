# Toolbar update policy

Raw-branch toolbar auto-update is retired. `toolbar.js` is delivered only inside
an exact Extella Client release bundle whose size, SHA-256, file inventory, and
source revisions are verified before installation.

The UI does not expose a self-update action. `wz_self_update` is informational:
it reports the installed release and directs the user to the verified
Repair/Update path without downloading or modifying files.

Do not reintroduce polling of `raw main`, marker-only validation, or replacement
of a live toolbar outside the transactional client installer.

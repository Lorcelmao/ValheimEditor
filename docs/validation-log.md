# In-game validation log

Each entry records an edited save that was loaded in Valheim (see `docs/usage-guide.md` for the procedure).
Game build fingerprint: `docs/spec-fingerprints.json`.

| Date | Game | Feature | Edit | Result | Evidence |
|------|------|---------|------|--------|----------|
| 2026-09-11 | 1.0.7 | Skills editing | `skills set Run=50 WoodCutting=25 Swim=10` (Swim newly added) on a copy of the local character | **Pass**: loaded, values shown in the Skills panel, played, and re-saved by the game | User confirmation. The re-saved file was not kept, so no `verify`/`diff` output was captured |

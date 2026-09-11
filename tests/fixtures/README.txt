Drop local Valheim .fch saves here to run the sample-dependent tests.
*.fch files are gitignored: they contain your character name and player ID.
If this folder has no .fch, tests fall back to ../../Save/*.fch, else they skip.
Treat fixtures as read-only; tests never modify them.

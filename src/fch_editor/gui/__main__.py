"""`python -m fch_editor.gui` — open the GUI directly."""
import sys
from pathlib import Path

from .app import main

if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)

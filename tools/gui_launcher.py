"""PyInstaller entry point for the packaged GUI.

A separate script (rather than pointing PyInstaller at the `fch_editor.gui`
package directly) keeps the analysis simple: one file, one import, no `-m`.
"""
from fch_editor.gui.app import main

if __name__ == "__main__":
    main()

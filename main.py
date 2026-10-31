"""Soundscape Previewer - preview Source engine soundscapes outside the game."""
import sys

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        # settings.py reads SSP_DATA_DIR on import, so the test sets it up first
        from soundscape_previewer import selftest

        i = sys.argv.index("--self-test")
        sys.exit(selftest.run(sys.argv[i + 1] if len(sys.argv) > i + 1 else None))

    from soundscape_previewer.ui.main_window import run

    sys.exit(run())

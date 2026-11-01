"""About text, shown by Help → About and the About tab of Preferences."""
from __future__ import annotations

from .. import __version__

WIKI_URL = "https://developer.valvesoftware.com/wiki/Soundscape"
REPO_URL = "https://github.com/Midlou/Source-Engine-Soundscape-Previewer"


def about_title() -> str:
    return (
        f"<h3>Soundscape Previewer {__version__}</h3>"
        "Preview Source engine soundscapes outside the game, with live editing."
    )


def about_body() -> str:
    return (
        "<p><b>Developed by AI</b><br>"
        "The code was written by <a href='https://www.anthropic.com/claude'>Claude</a> (Anthropic), "
        "an AI model.</p>"
        "<p><b>Directed by</b> Midlou<br>"
        "Features, testing and change requests.<br>"
        f"<a href='{REPO_URL}'>{REPO_URL}</a></p>"
        "<p><b>Built with</b><br>"
        "<a href='https://doc.qt.io/qtforpython-6/'>Qt for Python (PySide6)</a> - LGPL v3<br>"
        "<a href='https://numpy.org/'>NumPy</a> - BSD<br>"
        "<a href='https://python-sounddevice.readthedocs.io/'>python-sounddevice</a> / PortAudio - MIT<br>"
        "<a href='https://python-soundfile.readthedocs.io/'>python-soundfile</a> / "
        "<a href='https://libsndfile.github.io/libsndfile/'>libsndfile</a> - BSD / LGPL</p>"
        "<p><b>References</b><br>"
        f"<a href='{WIKI_URL}'>Valve Developer Community: Soundscape</a></p>"
        "<p><b>License</b><br>"
        "Released under the MIT License. Not affiliated with or endorsed by Valve Corporation. "
        "Source, Team Fortress 2 and Valve are trademarks of Valve Corporation. "
        "Game sounds are read from your own installation and are not included.</p>"
    )

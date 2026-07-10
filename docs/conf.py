# Sphinx configuration for the PyAutoScientist docs, published on
# ReadTheDocs as the `pyautoscientist` project from PyAutoBrain/docs/.
# The docs describe the whole organism; Brain hosts them because it owns
# the canonical organism prose (ORGANISM.md) and the growth rule says no
# new organs by default.

project = "PyAutoScientist"
author = "James Nightingale"
copyright = "2026, James Nightingale"

extensions = ["myst_parser"]
myst_enable_extensions = ["colon_fence"]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_title = "PyAutoScientist"
html_short_title = "PyAutoScientist"
html_permalinks_icon = "<span>#</span>"
html_last_updated_fmt = "%b %d, %Y"

html_show_sourcelink = False
html_show_sphinx = True
html_show_copyright = True

language = "en"

html_static_path = ["_static"]
html_css_files = ["pyauto.css"]

html_theme_options = {
    "light_css_variables": {
        "color-brand-primary": "#be123c",
        "color-brand-content": "#be123c",
    },
    "dark_css_variables": {
        "color-brand-primary": "#fb7185",
        "color-brand-content": "#fb7185",
    },
}

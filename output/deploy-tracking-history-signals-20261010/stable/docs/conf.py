# -- Sphinx configuration for easy-tdx ---------------------------------------
project = "easy-tdx"
copyright = "2025, Justin Gu"
author = "Justin Gu"


# The full version, including alpha/beta/rc tags
# Read from package metadata to keep single source of truth (pyproject.toml)
def _get_version() -> str:
    from importlib.metadata import version

    return version("easy-tdx")


release = _get_version()

# -- Extensions ---------------------------------------------------------------
extensions = [
    "myst_parser",
]

# -- MyST parser config -------------------------------------------------------
myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

# Suppress cross-reference warnings for relative links (e.g. docs/*.md, LICENSE)
suppress_warnings = ["myst.xref_missing"]

# -- HTML output --------------------------------------------------------------
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 3,
}

# -- Source suffix -------------------------------------------------------------
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

"""Static files follow the UI rule: every value comes from tokens.css (AC-50).

- The served tokens.css is an exact copy of docs/ui/tokens.css.
- app.css uses only var(--...) for colours and sizes, plus a short list of literal values.
- The Inter font is served by the app, never loaded from Google.
"""

import re
from pathlib import Path

from django.conf import settings

STATIC = Path(settings.BASE_DIR, "static", "cockpit")
APP_CSS = STATIC / "app.css"

# The only literal lengths app.css may use (decisions I-7, T-1 and the H1 letter-spacing on #23):
# 0, hairlines and focus outline (1px, 2px), the fixed sizes ui-spec names (3px selection bar,
# 6px pill dot, 28px timeline circle), the 899px breakpoint, full viewport height, and the H1
# letter-spacing from tokens.css.
ALLOWED_LENGTHS = frozenset({"1px", "2px", "3px", "6px", "28px", "899px", "100vh", "-0.01em"})
# Every CSS named colour. Only `transparent` and `currentColor` are allowed in app.css.
CSS_COLOUR_WORDS = frozenset(
    """
aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue
blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk
crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki
darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue
dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite
gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki
lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen
lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen
magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen
mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream
mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid
palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum
powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown
seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen
steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen
""".split()
)


def _css_without_comments(path: Path) -> str:
    return re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)


def _declaration_values(css: str) -> list[str]:
    """Every `property: value` value, without @font-face src lines (font file names)."""
    css = re.sub(r"@font-face\s*{[^}]*}", "", css)
    return re.findall(r":\s*([^;{}]+);", css)


def test_served_tokens_are_identical_to_the_ui_spec_tokens() -> None:
    source = Path(settings.BASE_DIR, "docs", "ui", "tokens.css").read_text()
    served = (STATIC / "tokens.css").read_text()

    assert served == source, "copy docs/ui/tokens.css to static/cockpit/tokens.css"


def test_access_css_was_merged_into_app_css() -> None:
    assert not (STATIC / "access.css").exists()


def test_app_css_has_no_colour_literals() -> None:
    css = _css_without_comments(APP_CSS)

    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "use a colour token, not a hex value"
    assert not re.search(r"\b(rgba?|hsla?)\(", css), "use a colour token, not rgb() or hsl()"
    words = {w.lower() for w in re.findall(r"[a-zA-Z]+", " ".join(_declaration_values(css)))}
    assert not (words & CSS_COLOUR_WORDS), f"named colours: {sorted(words & CSS_COLOUR_WORDS)}"


def test_app_css_lengths_come_from_tokens() -> None:
    css = _css_without_comments(APP_CSS)
    media_queries = re.findall(r"@media[^{]*", css)
    values = _declaration_values(css) + media_queries

    lengths = set()
    for value in values:
        lengths |= set(re.findall(r"-?\d*\.?\d+(?:px|em|rem|vh|vw|dvh|svh|lvh|vmin|vmax)\b", value))

    assert lengths <= ALLOWED_LENGTHS, f"not allowed: {sorted(lengths - ALLOWED_LENGTHS)}"


def test_the_only_em_value_is_the_h1_letter_spacing() -> None:
    css = _css_without_comments(APP_CSS)

    assert re.findall(r"[^;{}]*-0\.01em", css) == ["\n  letter-spacing: -0.01em"]


def test_inter_is_served_by_the_app_not_by_google() -> None:
    for weight in (400, 500, 600, 700):
        assert (STATIC / "fonts" / f"inter-latin-{weight}-normal.woff2").exists()
    assert (STATIC / "fonts" / "OFL.txt").exists()

    for folder in ("templates", "static", "cockpit"):
        for path in Path(settings.BASE_DIR, folder).rglob("*"):
            if path.suffix in {".html", ".css", ".py"} and "tests" not in path.parts:
                assert "fonts.googleapis.com" not in path.read_text(), path

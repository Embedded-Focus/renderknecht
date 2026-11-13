import base64
import copy
import datetime
import importlib.resources
import logging
import os
import re
import shlex
import string
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from io import FileIO
from pathlib import Path
from zlib import compress

import httpx
import yaml
from graphviz import Source
from yaml import SafeLoader

from ..util import yaml as util_yaml
from ..util.pandoc_wrapper import determine_pandoc_arguments, pdf_engine

_RESOURCES = importlib.resources.files("renderknecht") / "resources"


def _resource_path(name: str) -> Path:
    return Path(str(_RESOURCES / name))


def _resolve_resource(specific_env_var: str, filename: str) -> Path | None:
    """Return the path to a resource file, or None to use the bundled default.

    Priority: specific env var > RESOURCES_DIR/<filename>
              > XDG_CONFIG_HOME/renderknecht/<filename> > bundled default.
    """
    if specific_env_var in os.environ:
        return Path(os.environ[specific_env_var])
    if "RESOURCES_DIR" in os.environ:
        candidate = Path(os.environ["RESOURCES_DIR"]) / filename
        if candidate.exists():
            return candidate
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    candidate = xdg_config / "renderknecht" / filename
    if candidate.exists():
        return candidate
    return None


def augment_authors(yaml_metadata: dict, authors: dict) -> dict:
    if yaml_metadata and "author" in yaml_metadata:
        result = copy.copy(yaml_metadata)
        result["author"] = [authors.get(author, author) for author in yaml_metadata["author"]]
        return result
    return yaml_metadata


_UPLOADS_DIR = Path("/hedgedoc/public/uploads")

_CREATOR = (
    f"renderknecht {os.environ.get('RENDERKNECHT_GIT_HASH', 'unknown')} "
    "(https://github.com/Embedded-Focus/renderknecht/)"
)

#: Load Source Code Pro as the code (monospace) font. Eisvogel only loads this
#: package itself when no `fontfamily` is set. Our default look needs
#: `fontfamily: sourcesanspro` on Debian trixie, so Eisvogel skips it and the
#: driver loads it instead. Code in this file owns the include, so that no
#: preamble file can lose the code font.
CODE_FONT_INCLUDE = "```{=latex}\n\\usepackage{sourcecodepro}\n```\n"

#: pdfLaTeX reads UTF-8 through the inputenc tables. Characters that the
#: tables do not list stop the build with "Unicode character ... not set up
#: for use with LaTeX". The superscript and subscript family is a common
#: case in physics and chemistry text (``e⁻``, ``10⁶``, ``H₂O``), and the
#: tables carry none of it. This block maps the family onto
#: `\textsuperscript` and `\textsubscript`, which work in every font the
#: document can set.
#:
#: The default engine is XeTeX (`DEFAULT_PDF_ENGINE`), which needs none of
#: this: it reads every Unicode character natively, so the driver adds the
#: block only when `PDF_ENGINE` opts back into pdfLaTeX. The driver owns the
#: block, for the same reason as the code font: a preamble file that replaces
#: the bundled one must not lose the mappings. A preamble that declares its
#: own `newunicodechar` mappings keeps the driver out, so a custom definition
#: wins.
UNICODE_CHAR_INCLUDE = (
    "```{=latex}\n"
    "\\usepackage{newunicodechar}\n"
    "\\newunicodechar{⁻}{\\textsuperscript{-}}\n"
    "\\newunicodechar{⁺}{\\textsuperscript{+}}\n"
    "\\newunicodechar{⁰}{\\textsuperscript{0}}\n"
    "\\newunicodechar{¹}{\\textsuperscript{1}}\n"
    "\\newunicodechar{²}{\\textsuperscript{2}}\n"
    "\\newunicodechar{³}{\\textsuperscript{3}}\n"
    "\\newunicodechar{⁴}{\\textsuperscript{4}}\n"
    "\\newunicodechar{⁵}{\\textsuperscript{5}}\n"
    "\\newunicodechar{⁶}{\\textsuperscript{6}}\n"
    "\\newunicodechar{⁷}{\\textsuperscript{7}}\n"
    "\\newunicodechar{⁸}{\\textsuperscript{8}}\n"
    "\\newunicodechar{⁹}{\\textsuperscript{9}}\n"
    "\\newunicodechar{ⁿ}{\\textsuperscript{n}}\n"
    "\\newunicodechar{₀}{\\textsubscript{0}}\n"
    "\\newunicodechar{₁}{\\textsubscript{1}}\n"
    "\\newunicodechar{₂}{\\textsubscript{2}}\n"
    "\\newunicodechar{₃}{\\textsubscript{3}}\n"
    "\\newunicodechar{₄}{\\textsubscript{4}}\n"
    "\\newunicodechar{₅}{\\textsubscript{5}}\n"
    "\\newunicodechar{₆}{\\textsubscript{6}}\n"
    "\\newunicodechar{₇}{\\textsubscript{7}}\n"
    "\\newunicodechar{₈}{\\textsubscript{8}}\n"
    "\\newunicodechar{₉}{\\textsubscript{9}}\n"
    "\\newunicodechar{₊}{\\textsubscript{+}}\n"
    "\\newunicodechar{₋}{\\textsubscript{-}}\n"
    "\\newunicodechar{ₙ}{\\textsubscript{n}}\n"
    "```\n"
)

#: The one character that the default main font lacks. Source Sans Pro carries
#: the whole superscript and subscript family except the subscript n (`ₙ`),
#: which would print as a blank. Under XeTeX, the font's own superscript and
#: subscript glyphs are better than what `\textsuperscript` fakes, so the
#: driver maps only this one character. Under pdfLaTeX, the full family needs
#: the mapping above instead.
UNICODE_CHAR_XETEX_INCLUDE = (
    "```{=latex}\n\\usepackage{newunicodechar}\n\\newunicodechar{ₙ}{\\textsubscript{n}}\n```\n"
)

#: Landscape sheets for wide tables. A document asks for one with
#: `::: landscapepage`, and this code answers that request.
#:
#: The definition belongs to the driver, for the same reason as the code
#: font. A preamble loaded through `PREAMBLE_YAML`, `RESOURCES_DIR`, or
#: `~/.config/renderknecht/preamble.yaml` can replace the bundled preamble
#: file. A feature that this file drops is a feature a document loses
#: without warning. The driver wraps the definition in a check. If the
#: definition already exists, the driver skips it. A preamble file often
#: already carries the definition, so this is the normal case. Two
#: definitions in one build stop it with an error.
#:
#: `pdflscape` rotates the sheet for the viewer. It never touches the head
#: and foot that `scrlayer-scrpage` draws for Eisvogel. That head and foot
#: stay in portrait layer geometry, so they turn sideways with the rest of
#: the page.
#:
#: `\pagestyle{empty}` turns off this head and foot. This page style is
#: part of the LaTeX kernel, so it works with or without `scrlayer-scrpage`.
#: `\@oddhead` and `\@oddfoot` then draw a replacement. LaTeX draws this
#: replacement once per page, the same way it draws the original head and
#: foot. This also covers tables that run across several landscape sheets.
#:
#: The replacement uses TikZ absolute page coordinates and `\rotatebox{90}`
#: for position. It matches title, date, author, and page number to what
#: Eisvogel shows on a portrait page, with the same head and foot rule.
#:
#: This method avoids a conflict between `eso-pic` and `pdflscape`. With
#: `eso-pic`, a `\AddToShipoutPictureBG` background drops off the last page
#: of a multi-page `landscape` block. `\@oddhead` and `\@oddfoot` do not
#: have this problem. They are part of the LaTeX kernel's own per-page
#: output routine, not a third-party shipout hook that can race with
#: `pdflscape`'s own rotation code.
#:
#: `lscape` swaps `\textheight` for the portrait `\textwidth` to measure the
#: landscape page. This places the start of the body box at
#: `1in+\oddsidemargin` from the physical edge, the same offset, about
#: 2.5cm, where the head bar above sits. The body box also extends close to
#: where the foot bar sits.
#:
#: An earlier version of this code shrank only `\textheight`. This moved
#: the far end of the body box away from the foot. It did not move the
#: start, so the start stayed at the same point as the head. A test with a
#: table long enough to fill a sheet showed this problem. The foot had a
#: real gap. The head had only a small, incidental gap, by luck and not by
#: design.
#:
#: The current code pushes `\oddsidemargin` out by 2cm. This moves the
#: start of the body box away from the head. The code also shrinks
#: `\textheight` by 4cm: 2cm for the same shift at the start, and 2cm for
#: the foot, as before. `landscape` copies `\textheight` into `\@colht`,
#: `\@colroom`, and `\vsize`, so the code sets these three to the same new
#: value. A test confirmed the fix. Both ends of the body box now have the
#: same comfortable gap.
#:
#: Eisvogel sets every figure to `[H]` placement. A `[H]` figure never
#: floats to a later page, but it must still fit on the current page.
#:
#: Pandoc already helps with this. For any `\includegraphics` call with a
#: `width` but no `height`, pandoc adds `height=\textheight,keepaspectratio`.
#: A tall image then shrinks to fit `\textheight`.
#:
#: This shrink target was the same `\textheight` value just copied into
#: `\@colht`, `\@colroom`, and `\vsize`. It left no room for the caption
#: below the image. A `[H]` figure often sits alone on a landscape sheet,
#: with no other text. When the image alone already fills the full budget,
#: the caption does not fit. LaTeX then starts the figure on a fresh page,
#: and the page meant for it ships empty.
#:
#: A test confirmed this cause. Plain paragraphs on the same sheet, with
#: no figure, never lost a sheet. A figure, placed between two such
#: paragraphs, split the content onto three sheets. One sheet was blank,
#: one held the image, and one held the text after it.
#:
#: The code now shrinks `\textheight` by a further 2cm, after the copy to
#: `\@colht`, `\@colroom`, and `\vsize`. Pandoc's own image-fitting then
#: leaves that much room for the caption. The code does not touch the 2cm
#: page budget in `\@colht`, `\@colroom`, and `\vsize`, so a table still
#: gets the same capacity as before.
LANDSCAPE_INCLUDE = (
    "```{=latex}\n"
    "\\usepackage{pdflscape}\n"
    "\\usepackage{tikz}\n"
    "\\providecommand{\\blandscape}{\\begin{landscape}}\n"
    "\\providecommand{\\elandscape}{\\end{landscape}}\n"
    "\\makeatletter\n"
    "\\@ifundefined{landscapepage}{%\n"
    "\\newcommand{\\landscapepage@head}{%\n"
    "\\begin{tikzpicture}[remember picture,overlay]\n"
    "\\node[rotate=90,anchor=south west,inner sep=0pt] at "
    "([xshift=2.5cm,yshift=2.5cm]current page.south west)\n"
    "{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\normalfont\\upshape\\small \\@title\\hfil \\@date}};\n"
    "\\node[rotate=90,anchor=south west,inner sep=0pt] at "
    "([xshift=2.6cm,yshift=2.5cm]current page.south west)\n"
    "{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\leaders\\hrule height 0.4pt\\hfil}};\n"
    "\\end{tikzpicture}%\n"
    "}%\n"
    "\\newcommand{\\landscapepage@foot}{%\n"
    "\\begin{tikzpicture}[remember picture,overlay]\n"
    "\\node[rotate=90,anchor=north west,inner sep=0pt] at "
    "([xshift=\\dimexpr\\paperwidth-2.6cm\\relax,yshift=2.5cm]current page.south west)\n"
    "{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\leaders\\hrule height 0.4pt\\hfil}};\n"
    "\\node[rotate=90,anchor=north west,inner sep=0pt] at "
    "([xshift=\\dimexpr\\paperwidth-2.5cm\\relax,yshift=2.5cm]current page.south west)\n"
    "{\\hbox to \\dimexpr\\paperheight-5cm\\relax{\\normalfont\\upshape\\small \\@author\\hfil \\thepage}};\n"
    "\\end{tikzpicture}%\n"
    "}%\n"
    "\\newenvironment{landscapepage}{%\n"
    "\\clearpage\n"
    "\\pagestyle{empty}%\n"
    "\\blandscape\n"
    "\\addtolength{\\oddsidemargin}{2cm}%\n"
    "\\addtolength{\\textheight}{-4cm}%\n"
    "\\@colht=\\textheight\\relax\n"
    "\\@colroom=\\textheight\\relax\n"
    "\\vsize=\\textheight\\relax\n"
    "\\addtolength{\\textheight}{-2cm}%\n"
    "\\def\\@oddhead{\\landscapepage@head}%\n"
    "\\def\\@oddfoot{\\landscapepage@foot}%\n"
    "}{%\n"
    "\\elandscape\n"
    "\\clearpage\n"
    "\\@ifundefined{ps@eisvogel-header-footer}{}{\\pagestyle{eisvogel-header-footer}}%\n"
    "}\n"
    "}{}\n"
    "\\makeatother\n"
    "```\n"
)

#: The div class that binds a block to the landscape environment.
LANDSCAPE_ENVIRONMENT = "landscapepage"

#: Sheets of a different size. A document asks for one with `::: a3page`,
#: `::: a4page`, and the rest of the family below, and this code answers
#: that request.
#
#: The definition belongs to the driver, for the same reason as the landscape
#: definition above. A preamble file that replaces the bundled one would
#: otherwise lose the feature, without warning. The driver wraps the
#: definition in a check. If the environment already exists, the driver skips
#: it. Two definitions in one build stop it with an error.
#
#: A page of a different size is a different problem from a rotated page.
#: `pdflscape` only turns the sheet, so the paper stays A4. Here the paper
#: itself changes, and the text block must follow it. Eisvogel builds on the
#: KOMA-Script classes, and KOMA-Script owns both jobs:
#
#: `\KOMAoptions{paper=<spec>}` sets the new `\paperwidth` and `\paperheight`.
#: The option accepts a name such as `a3`, and a pair such as `297mm:420mm`.
#: The option does not recalculate the type area, and the code never runs
#: `\recalctypearea` for a sheet either. A recalculation is wrong for a
#: sheet, on two counts.
#
#: First, typearea caps the line width to what the font size can still read.
#: On A4 that cap sits above the text width, and nothing happens. On A3 the
#: cap binds: the text width comes out around 338pt, and the sheet is a
#: mostly empty page with a narrow strip of text. A diagram that asks for
#: `width=100%` gets `height=\textheight` from pandoc and shrinks with it.
#
#: Second, the document may not run its layout through typearea at all.
#: Eisvogel builds its type area with the geometry package, `margin=2.5cm`,
#: head and foot included. A recalculation replaces that layout with
#: typearea's own idea of the paper, and the page after the sheet carries
#: the wrong footer position. The code therefore never recalculates. It
#: captures the current layout at every sheet and grows the type area with
#: the paper, so the sheet keeps the margins of the document and
#: the page after the sheet gets its own layout back, value by value.
#
#: The code updates the output routine copies `\@colht`, `\@colroom`, and
#: `\vsize` itself, and `\linewidth` with them, because pandoc writes image
#: widths as fractions of `\linewidth`. KOMA-Script starts a new page for
#: the paper change itself. The code clears the page anyway, so the order is
#: safe on its own.
#
#: Every layout write is global, in the switch and in the restore. The
#: sheet's last page ships out inside the environment group, at the
#: `\clearpage` of the end code. The LaTeX output routine ends with
#: `\global\@colht\textheight` and `\global\vsize\@colroom`, so that
#: shipout writes the sheet's column height globally. A local switch would
#: revert at the group end, but those copies would not: the page after the
#: sheet would get a page box as tall as the sheet's, and its foot would
#: land below the paper edge, drawn but invisible. With global writes the
#: layout is one consistent state, and the restore, which runs after that
#: last shipout, overwrites all of it.
#
#: KOMA-Script writes `\pdfpagewidth` and `\pdfpageheight` once, at
#: `\begin{document}`. A later `paper` change does not reach the PDF page
#: size on its own, so the code writes both primitives after every paper
#: change. The primitives exist under pdfTeX and XeTeX. LuaTeX names them
#: `\pagewidth` and `\pageheight`. The build uses pdfTeX, and each write is
#: guarded, so the code stays quiet on any engine.
#
#: The code captures the paper and the layout at the start of every sheet,
#: as dimensions and not as a name. `paper=210mm:297mm` is a valid
#: `paper` value, and the restore writes the lengths back one by one. The
#: restore therefore works for every base paper and every way of building
#: the layout, geometry or typearea. A document that sets `papersize:` in
#: its front matter gets its own paper back, not a hard-coded A4. The
#: capture registers are assigned locally, inside the environment group, so
#: the nested groups act as a stack: a nested sheet restores the outer
#: sheet's layout, and the outer sheet restores the document's.
#
#: The capture and the restore cover the lengths of the page body. Twoside
#: documents keep their inner and outer margins through `\oddsidemargin`
#: alone in this code; a sheet in a twoside document gets the outer margin
#: of the recto pages. Eisvogel documents are onesided, and margin notes
#: have no place on a diagram sheet.
#
#: The Eisvogel head and foot need no replacement here. `scrlayer` stores the
#: geometry of every layer as an expression, and evaluates the expression once
#: per page, at shipout. The layers hold `\textwidth` and `\paperwidth`, so
#: they follow the new paper on the next sheet. This is why `landscapepage`
#: needs a hand-drawn head and foot and the sheet family does not: `pdflscape`
#: turns the page, and the layers do not know about the turn.
#
#: KOMA-Script warns when a type area option changes inside a group, and an
#: environment is a group. The warning asks for typesetting care, and the
#: care is already here: the code clears the page before and after the
#: change, so no material is measured with the old `\hsize`. The code
#: silences the warning around the `\KOMAoptions` call and restores the
#: check right after. The two silencing helpers use `\providecommand`, so a
#: preamble that defines them first wins.
#:
#: A figure grows with the sheet without extra markup. Pandoc fits an image to
#: `\linewidth` and `\textheight`, and both hold the new values inside the
#: environment. A Mermaid diagram with `width=100%` then spans the text block
#: of the changed sheet.
#
#: The sizes are a fixed family, not a parameter on one environment. The
#: `pandoc-latex-environment` filter turns a div into `\begin{name}` and
#: nothing else. A title attribute would arrive as a mandatory argument,
#: but a div without that attribute emits no braces at all. The environment
#: would then eat the first token of the content, silently. HedgeDoc, the
#: main authoring surface, edits plain `::: name` divs best. One environment
#: per size keeps every use to a plain div, and a typo in a size is a build
#: error instead of a mangled page. Documents that need a size outside the
#: family set `papersize:` in their front matter, which the base-paper
#: restore below respects.
SHEET_PAGE_SIZES: dict[str, str] = {
    "a3page": "a3",
    "a4page": "a4",
    "a5page": "a5",
    "b5page": "b5",
    "letterpage": "letter",
}


def _sheet_page_include(sizes: Iterable[str]) -> str:
    r"""Build the LaTeX block that defines the given sheet environments.

    Each environment gets its own `\@ifundefined` guard. The driver can
    therefore append an include that defines only the sizes a document or
    a preamble does not already define, and a document's own copy of one
    size never collides with the family.

    The paper change lives in three helpers shared by every size: one that
    captures the current paper and layout, and one each for switching and
    restoring. Every environment captures on entry, into registers local to
    its group, so nested sheets restore level by level. The switch and the
    restore write globally, because the output routine globalizes the
    column height while the sheet's last page ships out. The helpers are
    defined once, under their own guard, so a preamble that wants its own
    version can provide it first.

    :param sizes: The sheet environments to define. Each name must be a key
        of :data:`SHEET_PAGE_SIZES`.
    :returns: A raw LaTeX block for ``header-includes``.
    :raises ValueError: if a name is not a key of :data:`SHEET_PAGE_SIZES`.
    """
    for name in sizes:
        if name not in SHEET_PAGE_SIZES:
            raise ValueError(f"Unknown sheet environment: {name}")
    lines = [
        "```{=latex}",
        "\\makeatletter",
        "\\@ifundefined{renderknecht@switchpaper}{%",
        # One allocation of the capture registers. The captures themselves
        # happen per environment and stay local to its group.
        "\\newdimen\\renderknecht@base@paperwidth",
        "\\newdimen\\renderknecht@base@paperheight",
        "\\newdimen\\renderknecht@base@textwidth",
        "\\newdimen\\renderknecht@base@textheight",
        "\\newdimen\\renderknecht@base@oddsidemargin",
        "\\newdimen\\renderknecht@base@topmargin",
        "\\newdimen\\renderknecht@base@headheight",
        "\\newdimen\\renderknecht@base@headsep",
        "\\newdimen\\renderknecht@base@footskip",
        "\\providecommand*{\\renderknecht@silencegroupleveltest}{%",
        "\\@ifundefined{scr@grouplevel@test}{}{%",
        "\\let\\renderknecht@saved@groupleveltest\\scr@grouplevel@test",
        "\\let\\scr@grouplevel@test\\@gobble",
        "}%",
        "}%",
        "\\providecommand*{\\renderknecht@restategroupleveltest}{%",
        "\\@ifundefined{renderknecht@saved@groupleveltest}{}{%",
        "\\let\\scr@grouplevel@test\\renderknecht@saved@groupleveltest",
        "}%",
        "}%",
        "\\newcommand{\\renderknecht@capturelayout}{%",
        "\\renderknecht@base@paperwidth=\\paperwidth",
        "\\renderknecht@base@paperheight=\\paperheight",
        "\\renderknecht@base@textwidth=\\textwidth",
        "\\renderknecht@base@textheight=\\textheight",
        "\\renderknecht@base@oddsidemargin=\\oddsidemargin",
        "\\renderknecht@base@topmargin=\\topmargin",
        "\\renderknecht@base@headheight=\\headheight",
        "\\renderknecht@base@headsep=\\headsep",
        "\\renderknecht@base@footskip=\\footskip",
        "}%",
        # The switch grows the type area by the paper delta and keeps the
        # captured margins, so the sheet fills the paper the way the document
        # fills its own paper. A recalculated type area would cap the line
        # width to the font size and leave the sheet mostly empty; a wide
        # diagram would shrink with the strip that is left over.
        "\\newcommand{\\renderknecht@switchpaper}[1]{%",
        "\\renderknecht@silencegroupleveltest",
        "\\KOMAoptions{paper=#1}%",
        "\\renderknecht@restategroupleveltest",
        # Every write below is global. The sheet's own last page ships out
        # inside the environment group, and the LaTeX output routine then
        # writes `\vsize`, `\@colht`, and `\@colroom` globally from the
        # sheet's `\textheight`. Local writes would revert at the group end,
        # but those three would not, and the page after the sheet would get
        # the sheet's column height: its foot lands below the paper edge.
        # Global writes keep the whole layout in one state, and the restore
        # overwrites all of it after that last shipout.
        "\\global\\paperwidth=\\paperwidth",
        "\\global\\paperheight=\\paperheight",
        # The type area grows with the paper, the margins stay. Both margins
        # together own the same space as on the base paper, split as before.
        "\\global\\textwidth=\\dimexpr\\renderknecht@base@textwidth+\\paperwidth-\\renderknecht@base@paperwidth\\relax",
        "\\global\\textheight=\\dimexpr\\renderknecht@base@textheight+\\paperheight-\\renderknecht@base@paperheight\\relax",
        # The margins, the head, and the foot keep the captured values, so
        # nothing the paper option changes wins over the document's layout.
        "\\global\\oddsidemargin=\\renderknecht@base@oddsidemargin",
        "\\global\\topmargin=\\renderknecht@base@topmargin",
        "\\global\\headheight=\\renderknecht@base@headheight",
        "\\global\\headsep=\\renderknecht@base@headsep",
        "\\global\\footskip=\\renderknecht@base@footskip",
        "\\global\\hsize=\\textwidth",
        "\\global\\linewidth=\\textwidth",
        "\\global\\@colht=\\textheight",
        "\\global\\@colroom=\\textheight",
        "\\global\\vsize=\\textheight",
        "\\ifdefined\\pdfpagewidth\\global\\pdfpagewidth=\\paperwidth\\fi",
        "\\ifdefined\\pdfpageheight\\global\\pdfpageheight=\\paperheight\\fi",
        "}%",
        # The restore writes every captured length back, globally, after the
        # sheet's last page is out. No recalculation: typearea's own idea of
        # the base paper would move the footer of the page after the sheet,
        # because Eisvogel builds its layout with the geometry package and
        # not with the typearea divisor.
        "\\newcommand{\\renderknecht@restorepaper}{%",
        "\\global\\paperwidth=\\renderknecht@base@paperwidth",
        "\\global\\paperheight=\\renderknecht@base@paperheight",
        "\\global\\textwidth=\\renderknecht@base@textwidth",
        "\\global\\textheight=\\renderknecht@base@textheight",
        "\\global\\oddsidemargin=\\renderknecht@base@oddsidemargin",
        "\\global\\topmargin=\\renderknecht@base@topmargin",
        "\\global\\headheight=\\renderknecht@base@headheight",
        "\\global\\headsep=\\renderknecht@base@headsep",
        "\\global\\footskip=\\renderknecht@base@footskip",
        "\\global\\hsize=\\textwidth",
        "\\global\\linewidth=\\textwidth",
        "\\global\\@colht=\\textheight",
        "\\global\\@colroom=\\textheight",
        "\\global\\vsize=\\textheight",
        "\\ifdefined\\pdfpagewidth\\global\\pdfpagewidth=\\paperwidth\\fi",
        "\\ifdefined\\pdfpageheight\\global\\pdfpageheight=\\paperheight\\fi",
        "}%",
        "}{}",
    ]
    for name in sizes:
        lines += [
            f"\\@ifundefined{{{name}}}{{%",
            f"\\newenvironment{{{name}}}{{%",
            "\\clearpage",
            # Every sheet captures the layout it starts from. The capture is
            # local to the environment group, so the groups form a stack: a
            # nested sheet restores the outer sheet's layout, and the outer
            # sheet restores the document's.
            "\\renderknecht@capturelayout",
            f"\\renderknecht@switchpaper{{{SHEET_PAGE_SIZES[name]}}}%",
            "}{%",
            "\\clearpage",
            "\\renderknecht@restorepaper",
            "}",
            "}{}",
        ]
    lines += ["\\makeatother", "```"]
    return "\n".join(lines) + "\n"


#: The full family of sheet environments, as one include. The driver appends
#: this block when the preamble and the document define none of the sizes.
SHEET_PAGE_INCLUDE = _sheet_page_include(SHEET_PAGE_SIZES)

#: The font family that keeps the look Eisvogel would bring with its default
#: `sourcesans` package. That package is gone from Debian trixie, so trixie's
#: equivalent `sourcesanspro` takes its place. The `default` option is needed,
#: because the package only defines the family. Without it the document keeps
#: the serif font LaTeX starts with.
DEFAULT_FONT_METADATA = {
    "fontfamily": "sourcesanspro",
    "fontfamilyoptions": ["default"],
}

#: The main font that XeTeX needs by its real family name. Eisvogel loads the
#: package `sourcesans` as its default font under XeTeX, but no document sets
#: a font family through it, and Debian trixie ships the older package name
#: `sourcesanspro` only. Setting `mainfont` makes Eisvogel skip that block
#: and pick the font through fontspec instead, which knows the OpenType fonts
#: that `texlive-fonts-extra` ships. The code font comes from the
#: `sourcecodepro` include above, the math font from `fonts-lmodern`.
DEFAULT_MAINFONT = "Source Sans Pro"


def _as_include_list(value: object) -> list[str]:
    """Return a header-includes value as a list of LaTeX include strings.

    :param value: A header-includes value: None, a string, or a sequence of
        strings.
    :returns: The includes as a list of strings. None becomes an empty list.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _as_class_list(value: object) -> list[str]:
    """Return one pandoc-latex-environment value as a list of div classes.

    :param value: The classes bound to a LaTeX environment: None, a string, or
        a sequence of strings.
    :returns: The classes as a list of strings. None becomes an empty list.
    """
    return _as_include_list(value)


def _merge_environments(preamble: object, document: object) -> dict[str, list[str]]:
    """Combine the preamble's and the document's pandoc-latex-environment maps.

    A plain ``**`` merge lets the document replace the whole map. A document
    that adds one class then loses every class from the preamble, without
    warning. Merging per environment keeps both maps. The code drops an exact
    duplicate class. If it keeps the duplicate, the filter wraps the content
    twice.

    :param preamble: The map from the preamble file.
    :param document: The map from the document's front matter.
    :returns: The combined map, with the preamble's entries first.
    """
    combined: dict[str, list[str]] = {}
    for source in (preamble, document):
        if not isinstance(source, dict):
            continue
        for name, classes in source.items():
            merged = combined.get(str(name), [])
            merged.extend(_as_class_list(classes))
            combined[str(name)] = list(dict.fromkeys(merged))
    return combined


def embed_images(markdown: str) -> str:
    """Rewrite HedgeDoc upload URLs to local filesystem paths.

    Replaces any absolute URL pointing to ``/uploads/`` with a path under
    :data:`_UPLOADS_DIR`, which must be mounted from the HedgeDoc uploads
    volume.  When the mount is absent (e.g. in wrapper/render mode), image
    URLs are left unchanged.

    :param markdown: Markdown text to process.
    :returns: Markdown with upload URLs replaced by local file paths.
    """
    if not _UPLOADS_DIR.is_dir():
        logging.debug("HedgeDoc uploads not mounted at %s. Not embedding images.", _UPLOADS_DIR)
        return markdown

    return re.sub(r"https?://[^/]+/uploads/", f"{_UPLOADS_DIR}/", markdown)


def render_graphviz(markup: str) -> str:
    return Source(markup).pipe(format="svg").decode("utf-8")


PLANTUML_ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase + "-_"
BASE64_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/"
BASE64_TO_PLANTUML = bytes.maketrans(BASE64_ALPHABET.encode("utf-8"), PLANTUML_ALPHABET.encode("utf-8"))


def render_plantuml(markup: str) -> str:
    # see: https://github.com/dougn/python-plantuml/blob/master/plantuml.py
    zlibbed_str = compress(markup.encode("utf-8"))
    compressed_string = zlibbed_str[2:-4]
    encoded = base64.b64encode(compressed_string).translate(BASE64_TO_PLANTUML).decode("utf-8")
    response = httpx.get(f"http://plantuml:8080/svg/{encoded}")
    response.raise_for_status()
    return response.text


#: Path of the puppeteer configuration file. The image build creates this file.
#: It tells Chromium to run without its sandbox.
MERMAID_PUPPETEER_CONFIG = "/etc/renderknecht/puppeteer.json"


def render_mermaid(markup: str) -> bytes:
    """Render a Mermaid block to a PDF with the mmdc command.

    pandoc converts SVG to PDF with librsvg, which is the same SVG converter it
    uses for GraphViz and PlantUML. Mermaid SVG does not survive that step.
    librsvg drops the text inside ``<foreignObject>`` elements, which carry
    Mermaid labels by default. It drops text inside a group that holds a CSS
    ``filter`` or ``opacity`` declaration. It also drops the spaces between the
    per-word ``<tspan>`` elements that Mermaid writes. The diagram shapes stay, so
    the page looks nearly right without the text.

    mmdc renders with Chromium instead, so the PDF matches what a browser shows.
    This holds for every Mermaid diagram type.

    :param markup: Mermaid source code.
    :returns: The diagram as PDF bytes.
    :raises FileNotFoundError: if ``mmdc`` is not on PATH.
    :raises subprocess.CalledProcessError: if mmdc rejects the input, for example
        on invalid Mermaid syntax.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        source = Path(tmp_dir) / "diagram.mmd"
        target = Path(tmp_dir) / "diagram.pdf"
        source.write_text(markup, encoding="utf-8")

        command = ["mmdc", "-i", str(source), "-o", str(target), "--quiet"]
        if puppeteer_config := _puppeteer_config():
            command += ["-p", str(puppeteer_config)]
        command += shlex.split(os.environ.get("MERMAID_ARGS", ""))

        process = subprocess.run(command, capture_output=True)  # noqa: S603
        if process.returncode != 0:
            logging.error(
                "mmdc failed to render Mermaid: %s", process.stderr.decode(errors="replace").strip()
            )
            raise subprocess.CalledProcessError(process.returncode, command, process.stdout, process.stderr)
        return target.read_bytes()


def _puppeteer_config() -> Path | None:
    """Return the puppeteer configuration file to pass to mmdc, or None.

    The image ships a configuration file that turns off the Chromium sandbox.
    Chromium needs this, because it runs as root inside the container. That path
    usually does not exist outside the container. A developer who runs the CLI on
    their own machine is one example. mmdc then uses its own sandboxed defaults.

    :returns: Path to a puppeteer configuration file, or None to let mmdc use its
        own defaults.
    """
    candidate = Path(os.environ.get("MERMAID_PUPPETEER_CONFIG", MERMAID_PUPPETEER_CONFIG))
    return candidate if candidate.is_file() else None


Renderer = Callable[[str], str | bytes]


@dataclass(frozen=True)
class Tool:
    """A diagram tool together with the file extension of its output."""

    render: Renderer
    suffix: str


TOOLS: dict[str, Tool] = {
    "graphviz": Tool(render_graphviz, ".svg"),
    "mermaid": Tool(render_mermaid, ".pdf"),
    "plantuml": Tool(render_plantuml, ".svg"),
}

TemporaryFiles = list[FileIO]


def embed_diagrams(markdown: str, tmp_files: TemporaryFiles) -> str:
    """Replace diagram code blocks with references to the rendered diagrams.

    renderknecht renders each block that :data:`TOOLS` names into a temporary
    file, then replaces the block with a Markdown image. Pandoc embeds the
    diagram instead of printing the markup. The fence languages come from
    :data:`TOOLS`, so you add a tool in one place.

    :param markdown: Markdown to process.
    :param tmp_files: List that collects the temporary files for later cleanup.
    :returns: Markdown with diagram blocks replaced by image references.
    """
    fence = "|".join(sorted(TOOLS))

    def replace(match: re.Match) -> str:
        tool = TOOLS[match.group(1)]
        block_content = match.group(6)
        caption = match.group(3) if match.group(3) else ""
        # An attribute block that already starts with `{` goes through unchanged.
        # Pandoc reads one level of braces. Two levels give it text instead of an
        # attribute, so the braces stay in the PDF and pandoc-crossref finds no label.
        attributes = (match.group(5) or "").strip()
        formatting = attributes if attributes.startswith("{") else f"{{ {attributes} }}" if attributes else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=tool.suffix) as tmp_file:
            tmp_files.append(tmp_file)  # type: ignore
            rendered = tool.render(block_content)
            tmp_file.write(rendered if isinstance(rendered, bytes) else rendered.encode())
            return f"""
![{caption}]({tmp_file.name}){formatting}"""

    return re.sub(
        rf"```\s*({fence})(\s+\[(.*?)(\|(.*?))?\])?\n(.*?)```",
        replace,
        markdown,
        flags=re.DOTALL,
    )


def augment_yaml_preamble(hedgedoc_markdown: str) -> tuple[str, util_yaml.YAMLMetadata]:
    augmented_metadata = {}

    def replace(match: re.Match) -> str:
        nonlocal augmented_metadata
        preamble_path = _resolve_resource("PREAMBLE_YAML", "preamble.yaml")
        if preamble_path:
            with preamble_path.open(mode="r") as fh:
                preamble_data: util_yaml.YAMLMetadata = yaml.load(fh, Loader=SafeLoader)
            if preamble_data and "titlepage-logo" in preamble_data:
                logo = preamble_data["titlepage-logo"]
                if not Path(logo).is_absolute():
                    preamble_data["titlepage-logo"] = str(preamble_path.parent / logo)
        else:
            preamble_data = yaml.safe_load((_RESOURCES / "preamble.yaml").read_text())
            if preamble_data and "titlepage-logo" in preamble_data:
                preamble_data["titlepage-logo"] = str(_resource_path(preamble_data["titlepage-logo"]))
        if preamble_data is not None:
            augmented_metadata = preamble_data

        authors_path = _resolve_resource("AUTHORS_YAML", "authors.yaml")
        if authors_path:
            with authors_path.open(mode="r") as fh:
                authors = yaml.load(fh, Loader=SafeLoader) or {}
        else:
            authors = yaml.safe_load((_RESOURCES / "authors.yaml").read_text()) or {}

        yaml_metadata: util_yaml.YAMLMetadata = yaml.load(
            f"---\n{match.group(1)}",
            Loader=SafeLoader,
        )
        preamble_includes = _as_include_list(augmented_metadata.get("header-includes"))
        preamble_environments = augmented_metadata.get("pandoc-latex-environment")
        if yaml_metadata is not None:
            augmented_metadata = {**augmented_metadata, **yaml_metadata}
            # A header-includes entry in the document front matter would replace
            # the preamble entries in a plain ** merge. That silently drops the
            # code font and every other include. Keep both lists. Documents often
            # copy a preamble block verbatim, so drop exact duplicates. Two copies
            # would run \newcommand or \newtcolorbox twice and LaTeX stops with an
            # "already defined" error.
            if "header-includes" in yaml_metadata:
                combined = preamble_includes + _as_include_list(yaml_metadata["header-includes"])
                augmented_metadata["header-includes"] = list(dict.fromkeys(combined))
            # The same holds for pandoc-latex-environment: a document that adds
            # one class must not drop the box and landscape classes.
            if "pandoc-latex-environment" in yaml_metadata:
                augmented_metadata["pandoc-latex-environment"] = _merge_environments(
                    preamble_environments, yaml_metadata["pandoc-latex-environment"]
                )

        augmented_metadata = {
            **augmented_metadata,
            **augment_authors(augmented_metadata, authors),
        }

        if augmented_metadata and "titlepage-logo" in augmented_metadata:
            logo = augmented_metadata["titlepage-logo"]
            if not Path(logo).is_absolute() and not Path(logo).exists():
                resolved = _resolve_resource("", logo)
                if resolved:
                    augmented_metadata["titlepage-logo"] = str(resolved)

        if isinstance(augmented_metadata.get("date"), str) and augmented_metadata["date"].lower() == "today":
            augmented_metadata["date"] = datetime.date.today().isoformat()

        # The fonts belong to the driver, not to one preamble file. A config that
        # overrides fontfamily or header-includes must not lose Source Code Pro,
        # or code snippets fall back to Latin Modern Typewriter.
        augmented_metadata = {**DEFAULT_FONT_METADATA, **augmented_metadata}
        # Under XeTeX, Eisvogel needs a real `mainfont`, or it falls back to
        # the `sourcesans` package that Debian trixie does not ship. A
        # document that sets its own `mainfont` wins.
        if pdf_engine() != "pdflatex":
            augmented_metadata.setdefault("mainfont", DEFAULT_MAINFONT)
        code_font_includes = _as_include_list(augmented_metadata.get("header-includes"))
        if not any("sourcecodepro" in include for include in code_font_includes):
            code_font_includes.append(CODE_FONT_INCLUDE)
        augmented_metadata["header-includes"] = code_font_includes

        # The sheet environments and their class bindings go the same way.
        # The driver appends each include after the preamble blocks. A preamble
        # that uses `\newcommand` for the two helpers keeps its own version.
        # Our `\providecommand` stays quiet either way.
        driver_includes = _as_include_list(augmented_metadata.get("header-includes"))
        # The backslash in each check matters. The text `\renewenvironment` also
        # contains the word `newenvironment`, but without the backslash in
        # front of it. The check only matches text with the backslash, so it
        # does not match `\renewenvironment`. A document that only renews the
        # environment still needs the driver's copy of `\newenvironment`,
        # because there is nothing yet to renew.
        if not any("\\newenvironment{landscapepage}" in include for include in driver_includes):
            driver_includes.append(LANDSCAPE_INCLUDE)
        # A document may define its own copy of one size and still need the
        # rest of the family. The check runs per size, and the include that
        # goes out carries only the missing ones. Every environment in it is
        # guarded, so an overlap with a preamble copy stays harmless.
        missing_sheets = [
            name
            for name in SHEET_PAGE_SIZES
            if not any(f"\\newenvironment{{{name}}}" in include for include in driver_includes)
        ]
        if missing_sheets:
            driver_includes.append(_sheet_page_include(missing_sheets))

        # The Unicode character mappings go the same way. Under pdfLaTeX, the
        # full superscript and subscript family needs a mapping, because the
        # inputenc tables carry none of it. Under XeTeX, only the subscript n
        # needs one, because that is the one character the main font lacks.
        # A preamble or a document that loads newunicodechar itself owns the
        # mappings, and a second `\newunicodechar` for the same character stops
        # the build with an "already defined" error.
        owned = any("newunicodechar" in include for include in driver_includes)
        if not owned:
            if pdf_engine() == "pdflatex":
                driver_includes.append(UNICODE_CHAR_INCLUDE)
            else:
                driver_includes.append(UNICODE_CHAR_XETEX_INCLUDE)
        augmented_metadata["header-includes"] = driver_includes
        environments = _merge_environments(augmented_metadata.get("pandoc-latex-environment"), None)
        for sheet_environment in (LANDSCAPE_ENVIRONMENT, *SHEET_PAGE_SIZES):
            if sheet_environment not in environments.get(sheet_environment, []):
                environments.setdefault(sheet_environment, []).append(sheet_environment)
        augmented_metadata["pandoc-latex-environment"] = environments

        creator_block = (
            f"```{{=latex}}\n\\AtBeginDocument{{\\hypersetup{{pdfcreator={{{_CREATOR}}}}}}}\n```\n"
        )
        augmented_metadata.setdefault("header-includes", []).append(creator_block)

        return f"---\n{yaml.dump(augmented_metadata, default_flow_style=False, indent=2)}---"

    return re.sub(
        r"^---\s*(.*?)---",
        replace,
        hedgedoc_markdown,
        flags=re.DOTALL,
    ), augmented_metadata


def append_references(markdown: str, yaml_metadata: util_yaml.YAMLMetadata) -> str:
    if yaml_metadata and "references" in yaml_metadata:
        # Citeproc creates its own heading when the document explicitly sets
        # `reference-section-title`. Appending another one here would produce
        # duplicate headings. Without an override, keep the historical English
        # default and localize German documents from their BCP 47 language tag.
        if "reference-section-title" in yaml_metadata:
            return markdown
        language = yaml_metadata.get("lang")
        primary_language = (
            language.replace("_", "-").partition("-")[0].lower() if isinstance(language, str) else ""
        )
        title = "Literaturverzeichnis" if primary_language == "de" else "References"
        return f"{markdown}\n\n# {title}\n"
    return markdown


def prepare_markdown(hedgedoc_markdown: str, tmp_files: list[FileIO]) -> tuple[str, util_yaml.YAMLMetadata]:
    enriched_markdown, yaml_metadata = augment_yaml_preamble(hedgedoc_markdown)
    enriched_markdown = embed_diagrams(enriched_markdown, tmp_files)
    enriched_markdown = embed_images(enriched_markdown)
    enriched_markdown = append_references(enriched_markdown, yaml_metadata)

    return (
        enriched_markdown,
        yaml_metadata,
    )


def render_markdown(markdown: str, tmp_files: list[FileIO]) -> bytes:
    markdown, metadata = prepare_markdown(markdown, tmp_files)

    command = determine_pandoc_arguments(metadata)
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(input=markdown.encode())
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, " ".join(command), stdout, stderr)
    return stdout

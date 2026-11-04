"""Run the notebooks in order and save each, with its outputs, as notebooks/pdf/<name>.pdf.

    .venv/bin/python -m playwright install chromium    # once: the headless browser that prints the PDFs
    .venv/bin/python scripts/export_pdfs.py            # all notebooks, in run order (about 13 min)
    .venv/bin/python scripts/export_pdfs.py dataset_generation

Running a notebook rewrites its outputs in data/, exactly as running it by hand does.
"""
import sys
from pathlib import Path

import nbformat
from nbconvert import HTMLExporter
from nbconvert.preprocessors import ExecutePreprocessor
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ("dataset_generation", "deterministic_matching", "probabilistic_matching")  # run order
PRINT_CSS = """<style>  /* print every character: wrap long lines, fit wide tables to the page */
pre { white-space: pre-wrap !important; word-break: break-all; }
.jp-RenderedHTMLCommon table { table-layout: fixed; width: 100%; font-size: 8px; word-break: break-all; }
</style>"""


def main(names: list[str]) -> None:
    out = ROOT / "notebooks" / "pdf"
    out.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in names:
            path = ROOT / "notebooks" / f"{name}.ipynb"
            nb = nbformat.read(path, as_version=4)
            ExecutePreprocessor(timeout=None, kernel_name="python3").preprocess(nb, {"metadata": {"path": str(path.parent)}})
            html, _ = HTMLExporter(template_name="lab").from_notebook_node(nb)
            page = browser.new_page()
            page.set_content(html.replace("</head>", PRINT_CSS + "</head>"), wait_until="networkidle")
            page.pdf(path=str(out / f"{name}.pdf"), format="A4", landscape=True, print_background=True,
                     margin=dict(top="12mm", bottom="12mm", left="10mm", right="10mm"))
            print(f"notebooks/pdf/{name}.pdf")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:] or list(NOTEBOOKS))

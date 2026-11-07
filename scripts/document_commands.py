"""Write docs/commands.md, the reference of every nayose command, from the declarations in er/cli.py.

    .venv/bin/python scripts/document_commands.py      # after changing a command; a test fails until it is run
"""
import argparse

from er.cli import reference
from er.settings import project_root


def main() -> None:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args()
    path = project_root() / "docs" / "commands.md"
    path.write_text(reference() + "\n", encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

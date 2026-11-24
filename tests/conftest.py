"""What the tests share: a generated population for whole runs (design.generate, config/generator.toml, at 400
entities), made once for every test that runs one."""
import os
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# the processes the tests start import this checkout's nayose: the venv's editable install names the one it was made from
os.environ["PYTHONPATH"] = os.pathsep.join([str(ROOT), *filter(None, [os.environ.get("PYTHONPATH")])])


@pytest.fixture(scope="session")
def population():
    """A small generated population (design.generate.Generated: df, the records; truth, their entities): the tests
    count on it, so its spec is fixed here, households aside."""
    from design.generate import generate, load_reference, load_spec
    spec = replace(load_spec(ROOT / "config" / "generator.toml")[0], entities=400, households={})
    return generate(spec, *load_reference(ROOT / "data" / "reference"))

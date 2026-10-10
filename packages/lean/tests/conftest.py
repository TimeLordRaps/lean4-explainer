import pytest

from lean4_explainer import extensions
from lean4_explainer_lean import LeanExtension


@pytest.fixture(autouse=True)
def only_lean():
    extensions.activate([LeanExtension()])
    yield
    extensions.activate(None)

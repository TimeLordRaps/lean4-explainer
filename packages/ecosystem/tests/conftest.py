import pytest

from lean4_explainer import extensions
from lean4_explainer_ecosystem import EcosystemExtension


@pytest.fixture(autouse=True)
def only_ecosystem():
    extensions.activate([EcosystemExtension()])
    yield
    extensions.activate(None)

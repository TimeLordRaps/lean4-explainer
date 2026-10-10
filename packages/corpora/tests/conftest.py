import pytest

from lean4_explainer import extensions
from lean4_explainer_corpora import CorporaExtension


@pytest.fixture(autouse=True)
def only_corpora():
    extensions.activate([CorporaExtension()])
    yield
    extensions.activate(None)

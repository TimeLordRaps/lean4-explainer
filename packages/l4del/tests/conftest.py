import pytest

from lean4_explainer import extensions
from lean4_explainer.render import Context
from lean4_explainer_l4del import L4delExtension


@pytest.fixture(autouse=True)
def only_l4del():
    """These tests run with exactly the L4DEL extension active."""
    extensions.activate([L4delExtension()])
    yield
    extensions.activate(None)


@pytest.fixture
def make_context():
    def build(**overrides):
        values = {
            "title": "Test",
            "source_url": None,
            "source_ref": "main",
            "locations": {},
            "cross_links": True,
            "search": True,
        }
        values.update(overrides)
        return Context(**values)

    return build

import pytest

from lean4_explainer import extensions
from lean4_explainer.render import Context


@pytest.fixture(autouse=True)
def no_extensions():
    """The core suite runs with no extension active, whatever else is installed."""
    extensions.activate([])
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

import pytest

from lean4_explainer.render import Context


@pytest.fixture
def make_context():
    def build(**overrides):
        values = {
            "title": "Test",
            "source_url": None,
            "source_ref": "main",
            "locations": {},
            "glossary": {},
            "term_anchors": {},
            "term_pattern": None,
            "cross_links": True,
            "search": True,
            "learning_path": True,
        }
        values.update(overrides)
        return Context(**values)

    return build

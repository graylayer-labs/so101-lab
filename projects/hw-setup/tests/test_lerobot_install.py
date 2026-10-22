from importlib.metadata import version

PINNED = "0.6.1"


def test_lerobot_imports_at_the_pinned_version():
    # A broken install (missing extras, wrong wheel) fails here, not mid-session.
    import lerobot  # noqa: F401

    assert version("lerobot") == PINNED

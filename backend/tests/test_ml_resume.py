

def test_phrase_matcher_is_compiled_once_per_pipeline_and_path():
    """The ESCO matcher is expensive to build, so a second call must reuse the same object."""
    from ml.resume.skills import build_phrase_matcher, get_nlp  # imported here to keep module imports unchanged

    first = build_phrase_matcher(get_nlp())  # compiles (or hits cache from an earlier test)
    second = build_phrase_matcher(get_nlp())  # must be the identical cached tuple, not a rebuild
    assert first is second  # lru_cache returns the same tuple object

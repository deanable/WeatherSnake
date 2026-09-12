"""Tests for the WeatherSnake help system (content, CHM project, runtime registry)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_chm  # noqa: E402
import help_launcher  # noqa: E402

HELP_DIR = build_chm.HELP_DIR


# ---------------------------------------------------------------------------
# Help tree / CHM project
# ---------------------------------------------------------------------------
def test_help_tree_validates():
    """The umbrella check: everything below, all at once."""
    assert build_chm.validate_help_tree() == []


def test_topic_ids_are_contiguous_from_1000():
    ids = sorted(build_chm.TOPIC_IDS)
    assert ids == list(range(1000, 1021))


def test_every_topic_file_exists():
    for ctx_id, fname in build_chm.TOPIC_IDS.items():
        assert os.path.isfile(os.path.join(HELP_DIR, fname)), f"{ctx_id}: {fname}"


def test_every_topic_declares_charset_and_css():
    for fname in set(build_chm.TOPIC_IDS.values()):
        with open(os.path.join(HELP_DIR, fname), encoding="utf-8") as fh:
            raw = fh.read()
        assert "charset" in raw.lower(), fname
        assert 'href="styles.css"' in raw, fname


def test_hhp_alias_and_map_agree_with_topic_ids():
    sections = build_chm._parse_hhp_sections(build_chm.HHP_FILE)
    aliases = build_chm._hhp_aliases(sections["ALIAS"])
    ctxmap = build_chm._hhp_map(sections["MAP"])
    assert set(aliases) == set(ctxmap)
    for aid, fname in aliases.items():
        assert build_chm.TOPIC_IDS[ctxmap[aid]] == fname, aid


def test_hhp_defines_the_window_used_by_the_launcher():
    with open(build_chm.HHP_FILE, encoding="utf-8") as fh:
        content = fh.read()
    assert f"Default Window={build_chm.WINDOW_NAME}" in content
    assert f'{build_chm.WINDOW_NAME}="' in content  # [WINDOWS] block defines it


def test_contents_lists_every_topic():
    with open(build_chm.HHC_FILE, encoding="utf-8") as fh:
        content = fh.read()
    for fname in set(build_chm.TOPIC_IDS.values()):
        assert fname in content, f"{fname} missing from contents tree"


def test_index_has_key_keywords():
    with open(build_chm.HHK_FILE, encoding="utf-8") as fh:
        content = fh.read()
    for kw in ("F1 help", "CSV export", "Troubleshooting", "Units", "Location"):
        assert kw in content


def test_error_contexts_map_to_troubleshooting():
    assert build_chm.TOPIC_IDS[1019] == "troubleshooting.html"
    assert build_chm.TOPIC_IDS[1020] == "troubleshooting.html"


def test_topics_link_only_to_existing_files():
    """validate covers it; this asserts cross-links specifically stay resolvable."""
    errors = [e for e in build_chm.validate_help_tree() if "links missing file" in e]
    assert errors == []


def test_compile_without_hhc_returns_none(monkeypatch):
    monkeypatch.setattr(build_chm, "find_hhc", lambda: None)
    assert build_chm.compile_chm(verbose=False) is None


# ---------------------------------------------------------------------------
# Runtime launcher
# ---------------------------------------------------------------------------
class _FakeWidget:
    def __init__(self, master=None):
        self.master = master


def test_registry_direct_lookup():
    reg = help_launcher.HelpRegistry()
    w = _FakeWidget()
    reg.register(w, 1003)
    assert reg.lookup(w) == 1003


def test_registry_walks_up_to_parent():
    reg = help_launcher.HelpRegistry()
    parent = _FakeWidget()
    child = _FakeWidget(master=parent)
    reg.register(parent, 1004)
    assert reg.lookup(child) == 1004


def test_registry_falls_back_to_default():
    reg = help_launcher.HelpRegistry()
    assert reg.lookup(_FakeWidget()) == help_launcher.DEFAULT_CONTEXT_ID


def test_register_rejects_bad_ids():
    reg = help_launcher.HelpRegistry()
    w = _FakeWidget()
    reg.register(w, "not-a-number")
    assert reg.lookup(w) == help_launcher.DEFAULT_CONTEXT_ID


def test_register_help_convenience_and_reregistration():
    w = _FakeWidget()
    help_launcher.register_help(w, help_launcher.TOPIC_IDS["cli"])
    assert help_launcher.registry.lookup(w) == help_launcher.TOPIC_IDS["cli"]
    help_launcher.register_help(w, help_launcher.TOPIC_IDS["data"])
    assert help_launcher.registry.lookup(w) == help_launcher.TOPIC_IDS["data"]


def test_topic_file_resolution():
    assert help_launcher._topic_file(None) == "welcome.html"
    assert help_launcher._topic_file(1003) == "location.html"
    assert help_launcher._topic_file(99999) == "welcome.html"
    assert help_launcher._topic_file("bogus") == "welcome.html"


def test_html_topic_url_points_at_existing_file():
    url = help_launcher._html_topic_url("location.html")
    assert url.startswith("file://")
    assert os.path.isfile(url[len("file://"):])
    assert url.endswith("location.html")


def test_show_help_falls_back_to_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(help_launcher, "chm_path", lambda: None)
    monkeypatch.setattr(help_launcher.webbrowser, "open", lambda u: calls.append(u) or True)
    assert help_launcher.show_help(1015) == "browser"
    assert calls and calls[0].endswith("cli.html")


def test_show_help_unknown_context_uses_default_topic(monkeypatch):
    calls = []
    monkeypatch.setattr(help_launcher, "chm_path", lambda: None)
    monkeypatch.setattr(help_launcher.webbrowser, "open", lambda u: calls.append(u) or True)
    help_launcher.show_help(424242)
    assert calls and calls[0].endswith("welcome.html")


def test_show_topic_resolves_key(monkeypatch):
    calls = []
    monkeypatch.setattr(help_launcher, "chm_path", lambda: None)
    monkeypatch.setattr(help_launcher.webbrowser, "open", lambda u: calls.append(u) or True)
    assert help_launcher.show_topic("troubleshooting") == "browser"
    assert calls and calls[0].endswith("troubleshooting.html")


def test_chm_path_absent_in_source_tree_is_none_or_real():
    """In a source checkout the .chm is not compiled; the helper must not lie."""
    path = help_launcher.chm_path()
    assert path is None or (os.path.isfile(path) and path.endswith(".chm"))

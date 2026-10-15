# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the parts of the plugin that do not need a running QGIS.

atom_feed imports Qt through qgis.PyQt, so run them with the Python that comes
with QGIS (on Windows: the OSGeo4W Shell):  python -m pytest tests
"""

import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from inspire_atom_croatia.atom_feed import FeedError, municipality_id_from_href, parse_feed  # noqa: E402
from inspire_atom_croatia import cache  # noqa: E402
from inspire_atom_croatia.text_utils import fold_for_search, hr_sort_key, matches_search  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "atom_feed_sample.xml")


@pytest.fixture(scope="module")
def entries():
    with open(FIXTURE, "rb") as f:
        return parse_feed(f.read())


# --- feed parsing -----------------------------------------------------------

def test_parses_entries_and_skips_entries_without_zip(entries):
    assert len(entries) == 41  # 42 entries in the fixture, one has no zip link
    assert all(e.zip_url.endswith(".zip") for e in entries)


def test_first_entry_fields(entries):
    first = entries[0]
    assert first.name == "ČITLUK"
    assert first.municipality_id == "305570"
    assert first.epsg == "3765"
    assert first.crs_authid == "EPSG:3765"
    assert first.crs_label == "HTRS96/TM"
    assert first.updated == "2026-10-11T23:00:00Z"


def test_entry_without_category_has_empty_crs(entries):
    last = entries[-1]
    assert last.name == "BEZ KATEGORIJE"
    assert last.epsg == "" and last.crs_authid == ""


def test_duplicate_names_keep_distinct_ids(entries):
    bribir = [e.municipality_id for e in entries if e.name == "BRIBIR"]
    assert sorted(bribir) == ["302589", "329916"]


def test_id_from_href():
    assert municipality_id_from_href("https://x/atom/ko-305570.zip") == "305570"
    assert municipality_id_from_href("https://x/atom/something.zip") == ""


@pytest.mark.parametrize("content", [b"", b"not xml", b"<html><body/></html>",
                                     b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'])
def test_rejects_non_feed(content):
    with pytest.raises(FeedError):
        parse_feed(content)


BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE feed [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>&lol3;</title>
<link href="https://example.invalid/ko-1.zip"/></entry></feed>"""

EXTERNAL_ENTITY = b"""<?xml version="1.0"?>
<!DOCTYPE feed [<!ENTITY secret SYSTEM "file:///etc/passwd">]>
<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>&secret;</title>
<link href="https://example.invalid/ko-1.zip"/></entry></feed>"""


@pytest.mark.parametrize("content", [BILLION_LAUGHS, EXTERNAL_ENTITY])
def test_rejects_documents_with_dtd(content):
    with pytest.raises(FeedError, match="DTD"):
        parse_feed(content)


def test_ignores_foreign_namespaces_and_nested_elements():
    content = b"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:x="urn:x">
      <author><name>DGU</name></author>
      <entry>
        <x:title>wrong title</x:title>
        <title>Cadastral municipality TEST</title>
        <x:extra><link href="https://example.invalid/nested-ko-9.zip"/></x:extra>
        <link href="https://example.invalid/ko-7.zip"/>
      </entry>
    </feed>"""
    (entry,) = parse_feed(content)
    assert (entry.name, entry.municipality_id) == ("TEST", "7")


# --- Croatian sorting -------------------------------------------------------

def test_croatian_letter_order():
    words = ["ŽUPANJA", "ZADAR", "ČAKOVEC", "CRNI LUG", "ĆUNSKI", "DUBRAVA",
             "ĐURĐIC", "DONJI DRAGONOŽEC", "ŠIBENIK", "SVETI ĐURĐ"]
    assert sorted(words, key=hr_sort_key) == [
        "CRNI LUG", "ČAKOVEC", "ĆUNSKI", "DONJI DRAGONOŽEC", "DUBRAVA",
        "ĐURĐIC", "SVETI ĐURĐ", "ŠIBENIK", "ZADAR", "ŽUPANJA",
    ]


def test_digraphs_are_single_letters():
    # lj sorts after every other l-word, nj after every other n-word
    assert sorted(["LJUBEŠĆICA", "LOVRAN", "LIČKO CERJE"], key=hr_sort_key) == [
        "LIČKO CERJE", "LOVRAN", "LJUBEŠĆICA"]
    assert sorted(["NJIVICE", "NUGLA", "NEGOVEC"], key=hr_sort_key) == [
        "NEGOVEC", "NUGLA", "NJIVICE"]
    # dž comes after d but before đ
    assert sorted(["ĐAKOVO", "DŽEPIĆ", "DUGA RESA"], key=hr_sort_key) == [
        "DUGA RESA", "DŽEPIĆ", "ĐAKOVO"]


def test_prefix_and_space_sort_first():
    assert sorted(["BRDOVEC", "BRDO", "BRDO NOVO"], key=hr_sort_key) == [
        "BRDO", "BRDO NOVO", "BRDOVEC"]


def test_case_insensitive_and_decomposed_input():
    decomposed = "Čakovec"  # C + combining caron
    assert hr_sort_key(decomposed)[0] == hr_sort_key("ČAKOVEC")[0]


# --- search -----------------------------------------------------------------

def test_fold_for_search():
    assert fold_for_search("Đurđevac ČAKOVEC Šibenik Žepče Ćuk") == "durdevac cakovec sibenik zepce cuk"


def test_matches_search():
    assert matches_search("cakov", "ČAKOVEC", "302813")
    assert matches_search("3028", "ČAKOVEC", "302813")
    assert matches_search("brdo braj", "BRAJAKOVO BRDO", "307483")
    assert not matches_search("zadar", "ČAKOVEC", "302813")
    assert matches_search("   ", "anything")


def test_search_with_diacritics_is_exact():
    assert matches_search("ča", "ČAKOVEC")
    assert not matches_search("ča", "LJUBEŠĆICA")  # ća, not ča
    assert matches_search("ca", "LJUBEŠĆICA")      # plain query still folds
    assert matches_search("đurđ", "SVETI ĐURĐ") and not matches_search("đurđ", "DURDEVAC")


# --- cache ------------------------------------------------------------------

def _make_zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def test_extract_replaces_folder_and_deletes_zip(tmp_path):
    dest = cache.municipality_dir(str(tmp_path), "305570")
    os.makedirs(dest)
    (tmp_path / "ko-305570" / "stale.gml").write_text("old")
    zip_path = str(tmp_path / "download.zip")
    _make_zip(zip_path, {"CP.gml": "<x/>", "sub/BU.GML": "<x/>", "readme.txt": "hi"})

    files = cache.extract_zip(zip_path, dest)

    assert files == ["CP.gml", os.path.join("sub", "BU.GML")]
    assert not os.path.exists(zip_path)
    assert not os.path.exists(os.path.join(dest, "stale.gml"))
    assert not os.path.exists(dest + ".partial")


def test_bad_zip_leaves_existing_folder_untouched(tmp_path):
    dest = cache.municipality_dir(str(tmp_path), "1")
    os.makedirs(dest)
    (tmp_path / "ko-1" / "keep.gml").write_text("keep")
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"<html>error page</html>")

    with pytest.raises(cache.CacheError):
        cache.extract_zip(str(bad), dest)
    assert os.path.exists(os.path.join(dest, "keep.gml"))
    assert not os.path.exists(dest + ".partial")


def test_zip_slip_is_rejected(tmp_path):
    zip_path = str(tmp_path / "evil.zip")
    _make_zip(zip_path, {"../evil.gml": "x"})
    with pytest.raises(cache.CacheError):
        cache.extract_zip(zip_path, cache.municipality_dir(str(tmp_path), "2"))
    assert not (tmp_path / "evil.gml").exists()


def test_clear_unused_keeps_folders_in_use(tmp_path):
    root = str(tmp_path)
    for mid in ("1", "2", "3"):
        folder = cache.municipality_dir(root, mid)
        os.makedirs(folder)
        with open(os.path.join(folder, "CP.gml"), "w") as f:
            f.write("x" * 10)
    os.makedirs(os.path.join(root, "unrelated"))  # not ours, must survive
    in_use = [os.path.join(cache.municipality_dir(root, "2"), "CP.gml")]

    removed, freed, failed = cache.clear_unused(root, in_use)

    assert (removed, freed, failed) == (2, 20, [])
    assert sorted(os.listdir(root)) == ["ko-2", "unrelated"]

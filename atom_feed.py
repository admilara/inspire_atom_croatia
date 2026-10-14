# SPDX-License-Identifier: GPL-3.0-or-later
"""Parsing of the Croatian cadastral INSPIRE ATOM feed.

This module has no QGIS or Qt dependencies so it can be unit-tested with
plain Python.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

DEFAULT_FEED_URL = "https://oss.uredjenazemlja.hr/oss/public/atom/atom_feed.xml"

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

_TITLE_PREFIX = "Cadastral municipality "
_ID_FROM_HREF = re.compile(r"(\d+)\.zip$", re.IGNORECASE)
_EPSG_FROM_TERM = re.compile(r"EPSG(?:/\d+)?[/:](\d+)\s*$", re.IGNORECASE)


class FeedError(Exception):
    """Raised when the downloaded document is not a usable ATOM feed."""


@dataclass(frozen=True)
class FeedEntry:
    """One downloadable dataset (one cadastral municipality) in the feed."""

    name: str
    municipality_id: str
    zip_url: str
    epsg: str = ""
    crs_label: str = ""
    updated: str = ""

    @property
    def crs_authid(self):
        return f"EPSG:{self.epsg}" if self.epsg else ""


def _text(element, path):
    found = element.find(path, ATOM_NS)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _zip_link(entry):
    """Return the href of the entry's zip download, or "" if there is none."""
    for link in entry.findall("atom:link", ATOM_NS):
        href = (link.get("href") or "").strip()
        if href.lower().endswith(".zip"):
            return href
    return ""


def _crs(entry):
    for category in entry.findall("atom:category", ATOM_NS):
        match = _EPSG_FROM_TERM.search(category.get("term") or "")
        if match:
            return match.group(1), (category.get("label") or "").strip()
    return "", ""


def municipality_id_from_href(href):
    """'.../ko-305570.zip' -> '305570'. Returns "" if the pattern differs."""
    match = _ID_FROM_HREF.search(href)
    return match.group(1) if match else ""


def parse_feed(content):
    """Parse the feed document (bytes) into a list of FeedEntry.

    Entries without a zip link are skipped, since there is nothing to
    download for them.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise FeedError(f"The response is not valid XML ({exc}).") from exc

    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise FeedError("The response is XML, but not an ATOM feed.")

    entries = []
    for entry in root.findall("atom:entry", ATOM_NS):
        zip_url = _zip_link(entry)
        if not zip_url:
            continue
        title = _text(entry, "atom:title")
        if title.startswith(_TITLE_PREFIX):
            title = title[len(_TITLE_PREFIX):].strip()
        epsg, crs_label = _crs(entry)
        entries.append(
            FeedEntry(
                name=title,
                municipality_id=municipality_id_from_href(zip_url),
                zip_url=zip_url,
                epsg=epsg,
                crs_label=crs_label,
                updated=_text(entry, "atom:updated"),
            )
        )
    return entries

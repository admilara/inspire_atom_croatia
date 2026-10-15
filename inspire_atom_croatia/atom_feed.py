# SPDX-License-Identifier: GPL-3.0-or-later
"""Parsing of the Croatian cadastral INSPIRE ATOM feed.

The feed is downloaded from the internet, so it is parsed defensively with
Qt's streaming XML reader (QXmlStreamReader, shipped with every QGIS) instead
of Python's xml.etree:

- A document that contains a document type declaration (DTD) is rejected
  before its root element is read. ATOM feeds have no DTD, and refusing one
  removes the basis of XML entity attacks (entity-expansion "billion laughs",
  external entities).
- QXmlStreamReader never fetches external resources.

The module does not depend on QGIS itself, only on Qt through the qgis.PyQt
shim, so it works on both Qt5 (QGIS 3) and Qt6 (QGIS 4).
"""

import re
from dataclasses import dataclass

from qgis.PyQt.QtCore import QXmlStreamReader

DEFAULT_FEED_URL = "https://oss.uredjenazemlja.hr/oss/public/atom/atom_feed.xml"

ATOM_NS = "http://www.w3.org/2005/Atom"

_TOKEN = QXmlStreamReader.TokenType
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


def municipality_id_from_href(href):
    """'.../ko-305570.zip' -> '305570'. Returns "" if the pattern differs."""
    match = _ID_FROM_HREF.search(href)
    return match.group(1) if match else ""


def _is_atom(reader, local_name):
    return reader.namespaceUri() == ATOM_NS and reader.name() == local_name


def _read_entry(reader):
    """Read one <entry> element; the reader is positioned on its start tag.

    Returns a FeedEntry, or None if the entry has no zip download (then there
    is nothing to download for it).
    """
    title = updated = zip_url = epsg = crs_label = ""

    # readNextStartElement() returns False once the </entry> end tag is reached.
    while reader.readNextStartElement():
        if _is_atom(reader, "title"):
            title = reader.readElementText().strip()
        elif _is_atom(reader, "updated"):
            updated = reader.readElementText().strip()
        elif _is_atom(reader, "link"):
            href = reader.attributes().value("href").strip()
            if not zip_url and href.lower().endswith(".zip"):
                zip_url = href
            reader.skipCurrentElement()
        elif _is_atom(reader, "category"):
            match = _EPSG_FROM_TERM.search(reader.attributes().value("term"))
            if match and not epsg:
                epsg = match.group(1)
                crs_label = reader.attributes().value("label").strip()
            reader.skipCurrentElement()
        else:
            reader.skipCurrentElement()  # id, georss:polygon, ...

    if not zip_url:
        return None
    if title.startswith(_TITLE_PREFIX):
        title = title[len(_TITLE_PREFIX):].strip()
    return FeedEntry(
        name=title,
        municipality_id=municipality_id_from_href(zip_url),
        zip_url=zip_url,
        epsg=epsg,
        crs_label=crs_label,
        updated=updated,
    )


def parse_feed(content):
    """Parse the feed document (bytes) into a list of FeedEntry."""
    reader = QXmlStreamReader(bytes(content))
    entries = []
    root_seen = False

    while not reader.atEnd():
        token = reader.readNext()
        if token == _TOKEN.DTD:
            raise FeedError("The document contains a document type declaration (DTD), "
                            "which an ATOM feed never has. It was not processed.")
        if token != _TOKEN.StartElement:
            continue
        if not root_seen:
            root_seen = True
            if not _is_atom(reader, "feed"):
                raise FeedError("The response is XML, but not an ATOM feed.")
        elif _is_atom(reader, "entry"):
            entry = _read_entry(reader)
            if entry is not None:
                entries.append(entry)

    if reader.hasError():
        raise FeedError(f"The response is not valid XML ({reader.errorString()}, "
                        f"line {reader.lineNumber()}).")
    if not root_seen:
        raise FeedError("The response is empty or not XML.")
    return entries

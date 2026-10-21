# SPDX-License-Identifier: GPL-3.0-or-later
"""Main dialog: browse the feed, download a municipality, add its GML layers."""

import os
import tempfile
from datetime import datetime, timezone

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFileDownloader,
    QgsNetworkContentFetcher,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorLayer,
)
from qgis.gui import QgsMessageBar
from qgis.PyQt import sip, uic
from qgis.PyQt.QtCore import QSettings, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtNetwork import QNetworkReply
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHeaderView,
    QListWidgetItem,
    QMessageBox,
    QSizePolicy,
    QTableWidgetItem,
)

from . import cache
from .atom_feed import DEFAULT_FEED_URL, FeedError, parse_feed
from .text_utils import hr_sort_key, matches_search

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), "dialog.ui"))

SETTINGS_PREFIX = "inspire_atom_croatia/"
FEED_CACHE_NAME = "atom_feed.xml"

COL_NAME, COL_ID, COL_CRS, COL_UPDATED = range(4)
# Custom item data roles. PyQt6 enums are not ints, so take the value first.
_USER_ROLE = getattr(Qt.ItemDataRole.UserRole, "value", Qt.ItemDataRole.UserRole)
ENTRY_ROLE = _USER_ROLE
SORT_KEY_ROLE = _USER_ROLE + 1
SEARCH_TEXT_ROLE = _USER_ROLE + 2

# Qgis.LayerType replaced QgsMapLayerType in QGIS 3.30; QGIS 4 only has the new one.
if hasattr(Qgis, "LayerType"):
    VECTOR_LAYER_TYPE = Qgis.LayerType.Vector
else:  # QGIS < 3.30
    from qgis.core import QgsMapLayerType
    VECTOR_LAYER_TYPE = QgsMapLayerType.VectorLayer

CHECKED = Qt.CheckState.Checked
UNCHECKED = Qt.CheckState.Unchecked


def default_cache_dir():
    # qgisSettingsDirPath() uses forward slashes even on Windows; normalise the result.
    return cache.normalize_dir(
        os.path.join(QgsApplication.qgisSettingsDirPath(), "cache", "inspire_atom_croatia"))


def human_size(num_bytes):
    for unit in ("B", "kB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024


def parse_iso(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def layer_file_path(layer):
    """File path behind a layer, without OGR's '|layername=...' suffix."""
    # decodeUri() returns an empty dict for providers it cannot decode.
    decoded = QgsProviderRegistry.instance().decodeUri(layer.providerType(), layer.source())
    return decoded.get("path") or layer.source().split("|")[0]


class SortableItem(QTableWidgetItem):
    """Table item that sorts by a precomputed key instead of by display text."""

    def __lt__(self, other):
        mine, theirs = self.data(SORT_KEY_ROLE), other.data(SORT_KEY_ROLE)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


class InspireAtomDialog(QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.settings = QSettings()

        self.message_bar = QgsMessageBar(self)
        self.message_bar.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.messageBarLayout.addWidget(self.message_bar)

        self.entries = []
        self.selected = None
        self.feed_fetcher = None
        self.downloader = None
        self.download_target = None

        header = self.municipalityTable.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in (COL_ID, COL_CRS, COL_UPDATED):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.municipalityTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.progressBar.hide()

        self.feedUrlEdit.setText(self._setting("feed_url", DEFAULT_FEED_URL))
        self.cacheDirEdit.setText(self.cache_dir())

        self.loadFeedButton.clicked.connect(self.fetch_feed)
        self.resetUrlButton.clicked.connect(lambda: self.feedUrlEdit.setText(DEFAULT_FEED_URL))
        self.searchEdit.textChanged.connect(self.apply_filter)
        self.municipalityTable.itemSelectionChanged.connect(self.on_selection_changed)
        self.municipalityTable.itemDoubleClicked.connect(lambda _item: self.on_download_clicked())
        self.downloadButton.clicked.connect(self.on_download_clicked)
        self.selectAllCheck.toggled.connect(self.on_select_all_toggled)
        self.fileList.itemChanged.connect(self.update_add_button)
        self.addLayersButton.clicked.connect(self.add_selected_layers)
        self.browseCacheButton.clicked.connect(self.choose_cache_dir)
        self.openCacheButton.clicked.connect(self.open_cache_dir)
        self.clearCacheButton.clicked.connect(self.clear_unused_downloads)

        self.show_selection(None)
        self.load_cached_feed()

    # ----------------------------------------------------------------- settings

    def _setting(self, key, default=""):
        return self.settings.value(SETTINGS_PREFIX + key, default, type=str) or default

    def cache_dir(self):
        # Also normalises folders saved by earlier versions (QFileDialog returns '/' on Windows).
        return cache.normalize_dir(self._setting("cache_dir", default_cache_dir()))

    def choose_cache_dir(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr("Choose download folder"), self.cache_dir())
        if folder:
            folder = cache.normalize_dir(folder)
            self.settings.setValue(SETTINGS_PREFIX + "cache_dir", folder)
            self.cacheDirEdit.setText(folder)
            self.show_selection(self.selected)

    def open_cache_dir(self):
        os.makedirs(self.cache_dir(), exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.cache_dir()))

    # --------------------------------------------------------------------- feed

    def load_cached_feed(self):
        path = os.path.join(self.cache_dir(), FEED_CACHE_NAME)
        if not os.path.exists(path):
            self.countLabel.setText(self.tr("Click “Load feed” to get the list of municipalities."))
            return
        try:
            with open(path, "rb") as f:
                self.populate(parse_feed(f.read()))
        except (OSError, FeedError):
            return
        fetched = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        self.message_bar.pushInfo(
            self.tr("Saved feed"),
            self.tr("Showing the feed as loaded on {}. Click “Load feed” to refresh it.").format(fetched))

    def fetch_feed(self):
        url = self.feedUrlEdit.text().strip()
        if not url:
            self.message_bar.pushWarning(self.tr("Feed URL"), self.tr("Enter the URL of the ATOM feed."))
            return
        self.settings.setValue(SETTINGS_PREFIX + "feed_url", url)
        self.loadFeedButton.setEnabled(False)
        self.loadFeedButton.setText(self.tr("Loading…"))

        # QgsNetworkContentFetcher uses QGIS's network settings (proxy, SSL, timeouts)
        # and does not block the QGIS window while waiting.
        self.feed_fetcher = QgsNetworkContentFetcher()
        self.feed_fetcher.finished.connect(self.on_feed_fetched)
        self.feed_fetcher.fetchContent(QUrl(url))

    def on_feed_fetched(self):
        self.loadFeedButton.setEnabled(True)
        self.loadFeedButton.setText(self.tr("Load feed"))
        reply = self.feed_fetcher.reply()
        if reply is None or reply.error() != QNetworkReply.NetworkError.NoError:
            error = reply.errorString() if reply is not None else self.tr("no response")
            self.message_bar.pushCritical(self.tr("Could not load the feed"), error)
            return
        content = bytes(reply.readAll())
        try:
            entries = parse_feed(content)
        except FeedError as exc:
            self.message_bar.pushCritical(self.tr("Could not read the feed"), str(exc))
            return
        if not entries:
            self.message_bar.pushWarning(self.tr("Empty feed"), self.tr("The feed contains no downloadable datasets."))
            return

        try:
            os.makedirs(self.cache_dir(), exist_ok=True)
            with open(os.path.join(self.cache_dir(), FEED_CACHE_NAME), "wb") as f:
                f.write(content)
        except OSError:
            pass  # the cached copy is only a convenience
        self.populate(entries)
        self.message_bar.pushSuccess(self.tr("Feed loaded"), self.tr("{} cadastral municipalities.").format(len(entries)))

    def populate(self, entries):
        self.entries = entries
        table = self.municipalityTable
        table.setSortingEnabled(False)
        table.clearContents()
        table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            name = SortableItem(entry.name)
            name.setData(ENTRY_ROLE, entry)
            name.setData(SORT_KEY_ROLE, hr_sort_key(entry.name))
            name.setData(SEARCH_TEXT_ROLE, f"{entry.name} {entry.municipality_id}")

            ident = SortableItem(entry.municipality_id)
            ident.setData(SORT_KEY_ROLE, int(entry.municipality_id) if entry.municipality_id.isdigit() else -1)

            crs = QTableWidgetItem(" ".join(p for p in (entry.crs_authid, entry.crs_label) if p))
            updated = QTableWidgetItem(entry.updated.replace("T", " ").replace("Z", " UTC"))

            for col, item in ((COL_NAME, name), (COL_ID, ident), (COL_CRS, crs), (COL_UPDATED, updated)):
                table.setItem(row, col, item)
        table.setSortingEnabled(True)
        table.sortItems(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.apply_filter()

    def apply_filter(self):
        query = self.searchEdit.text()
        table = self.municipalityTable
        visible = 0
        for row in range(table.rowCount()):
            item = table.item(row, COL_NAME)
            show = item is not None and matches_search(query, item.data(SEARCH_TEXT_ROLE))
            table.setRowHidden(row, not show)
            visible += show
        if self.entries:
            self.countLabel.setText(self.tr("{} of {}").format(visible, len(self.entries)))

    # -------------------------------------------------------------- selection

    def on_selection_changed(self):
        rows = {index.row() for index in self.municipalityTable.selectedIndexes()}
        entry = None
        if len(rows) == 1:
            item = self.municipalityTable.item(rows.pop(), COL_NAME)
            entry = item.data(ENTRY_ROLE) if item else None
        self.show_selection(entry)

    def entry_dir(self, entry):
        return cache.municipality_dir(self.cache_dir(), entry.municipality_id)

    def show_selection(self, entry):
        self.selected = entry
        self.fileList.clear()
        self.selectAllCheck.setChecked(False)
        busy = self.downloader is not None
        if entry is None:
            self.selectionLabel.setText(self.tr("Select a cadastral municipality in the table."))
            self.downloadButton.setEnabled(False)
            self.downloadButton.setText(self.tr("Download"))
            self.update_add_button()
            return

        folder = self.entry_dir(entry)
        files = cache.list_vector_files(folder)
        lines = [f"<b>{entry.name}</b> (ID {entry.municipality_id}"
                 + (f", {entry.crs_authid} {entry.crs_label}" if entry.crs_authid else "") + ")"]
        if files:
            downloaded = datetime.fromtimestamp(os.path.getmtime(folder), tz=timezone.utc)
            line = self.tr("Downloaded {} ({}).").format(
                downloaded.astimezone().strftime("%Y-%m-%d %H:%M"), human_size(cache.folder_size(folder)))
            feed_time = parse_iso(entry.updated)
            if feed_time and feed_time > downloaded:
                line += " <b>" + self.tr("The feed entry was updated after this download.") + "</b>"
            lines.append(line)
            self.downloadButton.setText(self.tr("Download again"))
        else:
            self.downloadButton.setText(self.tr("Download"))
        self.selectionLabel.setText("<br>".join(lines))
        self.downloadButton.setEnabled(not busy)
        self.show_files(files)

    def show_files(self, files):
        self.fileList.blockSignals(True)
        self.fileList.clear()
        for relative in files:
            item = QListWidgetItem(relative)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(UNCHECKED)
            self.fileList.addItem(item)
        self.fileList.blockSignals(False)
        self.selectAllCheck.setEnabled(bool(files))
        self.update_add_button()

    def checked_files(self):
        return [self.fileList.item(i).text() for i in range(self.fileList.count())
                if self.fileList.item(i).checkState() == CHECKED]

    def on_select_all_toggled(self, checked):
        self.fileList.blockSignals(True)
        for i in range(self.fileList.count()):
            self.fileList.item(i).setCheckState(CHECKED if checked else UNCHECKED)
        self.fileList.blockSignals(False)
        self.update_add_button()

    def update_add_button(self, *_args):
        self.addLayersButton.setEnabled(bool(self.checked_files()))

    # --------------------------------------------------------------- download

    def paths_in_use(self):
        """File paths behind all layers in the current project.

        For non-file layers (WMS, PostGIS, memory, ...) this yields a URI or
        connection string, which simply never matches a cache folder.
        """
        return [layer_file_path(layer) for layer in QgsProject.instance().mapLayers().values()]

    def on_download_clicked(self):
        entry = self.selected
        if entry is None or self.downloader is not None:
            return
        folder = self.entry_dir(entry)
        if any(cache.is_inside(p, folder) for p in self.paths_in_use()):
            QMessageBox.information(
                self, self.tr("Files in use"),
                self.tr("Layers in the current project use the downloaded files of {}. "
                   "Remove those layers first, then download again.").format(entry.name))
            return

        os.makedirs(self.cache_dir(), exist_ok=True)
        handle, zip_path = tempfile.mkstemp(prefix=f"inspire_atom_{entry.municipality_id}_", suffix=".zip")
        os.close(handle)
        self.download_target = (entry, zip_path)

        self.progressBar.setRange(0, 0)
        self.progressBar.show()
        self.downloadButton.setEnabled(False)
        self.loadFeedButton.setEnabled(False)

        # QgsFileDownloader respects QGIS proxy/SSL settings, reports progress and
        # deletes itself once it has finished, failed or been cancelled.
        self.downloader = QgsFileDownloader(QUrl(entry.zip_url), zip_path, "", True)
        # The downloader calls deleteLater() on itself when done. Hand ownership
        # to C++ so Python does not delete it a second time (which crashes QGIS).
        sip.transferto(self.downloader, None)
        self.downloader.downloadProgress.connect(self.on_download_progress)
        self.downloader.downloadError.connect(self.on_download_error)
        self.downloader.downloadCompleted.connect(self.on_download_completed)
        self.downloader.downloadExited.connect(self.on_download_exited)
        self.downloader.startDownload()

    def on_download_progress(self, received, total):
        if total > 0:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(int(received * 100 / total))
            self.progressBar.setFormat(f"{human_size(received)} / {human_size(total)}")
        else:
            self.progressBar.setFormat(human_size(received))

    def on_download_error(self, errors):
        self.message_bar.pushCritical(self.tr("Download failed"), "; ".join(errors))

    def on_download_completed(self, *_args):
        entry, zip_path = self.download_target
        try:
            files = cache.extract_zip(zip_path, self.entry_dir(entry))
        except (cache.CacheError, OSError) as exc:
            self.message_bar.pushCritical(self.tr("Could not unpack the download"), str(exc))
            return
        if not files:
            self.message_bar.pushWarning(self.tr("No GML files"), self.tr("The archive of {} contains no GML files.").format(entry.name))
        else:
            self.message_bar.pushSuccess(self.tr("Downloaded"), self.tr("{}: {} file(s) ready to add.").format(entry.name, len(files)))

    def on_download_exited(self):
        _entry, zip_path = self.download_target
        if os.path.exists(zip_path):  # failed or cancelled download
            try:
                os.remove(zip_path)
            except OSError:
                pass
        self.downloader = None
        self.download_target = None
        self.progressBar.hide()
        self.loadFeedButton.setEnabled(True)
        self.show_selection(self.selected)

    def cancel_download(self):
        if self.downloader is not None:
            self.downloader.cancelDownload()

    # ---------------------------------------------------------------- layers

    def add_selected_layers(self):
        entry = self.selected
        files = self.checked_files()
        if entry is None or not files:
            return
        folder = self.entry_dir(entry)
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group_name = f"{entry.name} ({entry.municipality_id})"
        group = root.findGroup(group_name) or root.insertGroup(0, group_name)

        added, failed = 0, []
        for relative in files:
            path = os.path.join(folder, relative)
            layers = self.layers_from_file(path, entry)
            if not layers:
                failed.append(relative)
            for layer in layers:
                project.addMapLayer(layer, False)
                group.addLayer(layer)
                added += 1

        if failed:
            self.message_bar.pushWarning(self.tr("Some files could not be loaded"), ", ".join(failed))
        if added:
            self.iface.messageBar().pushSuccess(
                self.tr("INSPIRE ATOM Croatia"),
                self.tr("Added {} layer(s) to group “{}”.").format(added, group_name))

    def layers_from_file(self, path, entry):
        """One layer per vector sublayer in the file (a GML file may hold several feature types)."""
        base = os.path.splitext(os.path.basename(path))[0]
        uris = []
        for details in QgsProviderRegistry.instance().querySublayers(path):
            if details.type() == VECTOR_LAYER_TYPE:
                uris.append((details.uri(), details.name(), details.providerKey()))
        if not uris:
            uris = [(path, base, "ogr")]

        layers = []
        for uri, sub_name, provider in uris:
            name = base if len(uris) == 1 or not sub_name else f"{base} – {sub_name}"
            layer = QgsVectorLayer(uri, f"{entry.name} – {name}", provider)
            if not layer.isValid():
                continue
            if not layer.crs().isValid() and entry.crs_authid:
                layer.setCrs(QgsCoordinateReferenceSystem(entry.crs_authid))
            layers.append(layer)
        return layers

    # ----------------------------------------------------------------- cache

    def clear_unused_downloads(self):
        root = self.cache_dir()
        in_use = self.paths_in_use()
        candidates = [f for f in cache.cached_folders(root)
                      if not any(cache.is_inside(p, f) for p in in_use)]
        if not candidates:
            QMessageBox.information(self, self.tr("Nothing to clear"),
                                    self.tr("Every downloaded municipality is used by the current project."))
            return
        size = sum(cache.folder_size(f) for f in candidates)
        answer = QMessageBox.question(
            self, self.tr("Clear unused downloads"),
            self.tr("Delete {} downloaded municipalities ({}) that the current project does not use?\n\n"
               "Other saved projects that use these files will show them as missing layers.")
            .format(len(candidates), human_size(size)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed, freed, failed = cache.clear_unused(root, in_use)
        if failed:
            self.message_bar.pushWarning(self.tr("Some folders could not be deleted"), ", ".join(failed))
        self.message_bar.pushSuccess(self.tr("Cleared"), self.tr("{} municipalities removed, {} freed.").format(removed, human_size(freed)))
        self.show_selection(self.selected)

    # ------------------------------------------------------------------ misc

    def closeEvent(self, event):
        self.cancel_download()
        super().closeEvent(event)

    def reject(self):
        self.cancel_download()
        super().reject()

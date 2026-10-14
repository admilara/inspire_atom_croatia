# SPDX-License-Identifier: GPL-3.0-or-later
"""QGIS entry point: menu entry, toolbar button and translations."""

import os

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTranslator
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

PLUGIN_DIR = os.path.dirname(__file__)



class InspireAtomCroatiaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self.translator = None
        self._install_translator()

    def _install_translator(self):
        locale = (QSettings().value("locale/userLocale", "", type=str) or "")[:2]
        qm_path = os.path.join(PLUGIN_DIR, "i18n", f"inspire_atom_croatia_{locale}.qm")
        if locale and os.path.exists(qm_path):
            self.translator = QTranslator()
            if self.translator.load(qm_path):
                QCoreApplication.installTranslator(self.translator)
            else:
                self.translator = None

    def menu_name(self):
        return QCoreApplication.translate("InspireAtomCroatiaPlugin", "&INSPIRE ATOM Croatia")

    def initGui(self):
        self.action = QAction(
            QIcon(os.path.join(PLUGIN_DIR, "icon.svg")),
            QCoreApplication.translate("InspireAtomCroatiaPlugin", "Download cadastral data (INSPIRE ATOM)…"),
            self.iface.mainWindow(),
        )
        self.action.setObjectName("inspireAtomCroatiaAction")
        self.action.setWhatsThis(QCoreApplication.translate(
            "InspireAtomCroatiaPlugin",
            "Download cadastral parcels of Croatian cadastral municipalities "
            "from the DGU INSPIRE ATOM feed and add them as layers."))
        self.action.triggered.connect(self.run)
        self.iface.addPluginToWebMenu(self.menu_name(), self.action)
        self.iface.addWebToolBarIcon(self.action)

    def unload(self):
        if self.dialog is not None:
            self.dialog.cancel_download()
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        if self.action is not None:
            self.iface.removePluginWebMenu(self.menu_name(), self.action)
            self.iface.removeWebToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.translator is not None:
            QCoreApplication.removeTranslator(self.translator)
            self.translator = None

    def run(self):
        # Imported here so a missing dependency shows up when the dialog is
        # opened, not as a failure to load the whole plugin at QGIS startup.
        from .dialog import InspireAtomDialog

        if self.dialog is None:
            self.dialog = InspireAtomDialog(self.iface, self.iface.mainWindow())
        # Non-modal: the map stays usable while the dialog is open.
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()


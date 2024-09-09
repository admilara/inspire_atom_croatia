from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from qgis.core import *
from qgis.gui import *
from .croatomfeeddialog import CroAtomFeedDialog

class CroAtomFeed:

    def __init__(self, iface):
        # save ref to qgis interface
        self.iface = iface
        #self.plugin_dir = self.iface.pluginPath()
        #self.action = None

    def initGui(self):
        # start plugin config
        self.action = QAction("CRO ATOM FEED", self.iface.mainWindow())
        self.action.triggered.connect(self.run)

        # add toolbar button and menu item
        if hasattr(self.iface, "addPluginToWebMenu"):
            self.iface.addWebToolBarIcon(self.action)
            self.iface.addPluginToWebMenu("&Cro ATOM Feed", self.action)
        else:
            self.iface.addToolBarIcon(self.action)
            self.iface.addPluginToMenu("&Cro ATOM Feed", self.action)

    def unload(self):
        if hasattr(self.iface, "addPluginToWebMenu"):
            self.iface.removePluginWebMenu("&Cro ATOM Feed", self.action)
            self.iface.removeWebToolBarIcon(self.action)
        else:
            self.iface.removePluginMenu("&Cro ATOM Feed", self.action)
            self.iface.removeToolBarIcon(self.action)

    def about(self):
        infoString = "<table>" \
                     "<tr><td colspan=\"2\"><b>Croatian ATOM feed</b></td></tr><tr>" \
                     "<td colspan=\"2\">Experimental Plugin</td></tr>" \
                     "<tr><td colspan=\"2\"></td></tr>" \
                     "<tr><td rowspan=\"2\">Authors:</td>" \
                     "<td>Lara Buljan " \
                     "(<a href=\"mailto:lara.buljan@outlook.com\">lara.buljan@outlook.com</a>)</td></tr>" \
                     "<tr><td>Website:</td>" \
                     "<td><a href=\"https://github.com/\">" \
                     "https://github.com/</a></td></tr>" \
                     "<tr></tr>" \
                     "</table>"


    def run(self):
        dialog = CroAtomFeedDialog(self)
        dialog.show()
        result = dialog.exec_()
        if result == 1:
            # right now this serves to block user interaction while the dialog is up. might get changed later.
            pass
"""
/***************************************************************************
 Croatian INSPIRE ATOM Feed
                                 A QGIS plugin
 Client for INSPIRE Downloadservices based on ATOM-Feeds
                             -------------------
        begin                : September, 2024
        copyright            : (C) 2024 by Lara Buljan
        email                : lara.buljan@outlook.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from PyQt5 import uic
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtNetwork import *
from qgis.core import *
import os
import os.path
from datetime import date
import xml.etree.ElementTree as ET
import requests
from PyQt5.QtWidgets import QTableWidgetItem
import tempfile
import zipfile
from qgis.core import QgsVectorLayer, QgsProject

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'ui_croatomfeed.ui'))
plugin_path = os.path.abspath(os.path.dirname(__file__))

class CroAtomFeedDialog(QDialog, FORM_CLASS):
    def __init__(self, parent):
        super(CroAtomFeedDialog, self).__init__(None)
        self.setupUi(self)
        self.parent = parent
        self.iface = self.parent.iface
        self.root = QgsProject.instance().layerTreeRoot()

        # network manager
        self.qnam = QNetworkAccessManager()
        #self.qnam.authenticationRequired.connect(self.authenticationRequired)
        #self.qnam.sslErrors.connect(self.sslErrors)
        self.settings = QSettings()
        self.init_variables()

        # connect signals
        self.processXML.clicked.connect(self.on_process_xml_clicked)
        self.tableList.cellClicked.connect(self.on_table_item_clicked)
        self.listLayersButton.clicked.connect(self.on_list_layers_clicked)
        self.addLayerButton.clicked.connect(self.on_add_layer_clicked)

    def init_variables(self):
        self.onlineresource = ""
        self.layername = ""
        self.dataset_indexes = {}
        self.dataset_rep = {}
        self.current_metadata = {}

    def on_process_xml_clicked(self):
        url = self.txtUrl.text()
        if not url:
            QMessageBox.warning(self, title="Input error", text="Please enter oss.uredenazemlja XML link")
            return
        self.populate_table_with_xml_data(url)

    def populate_table_with_xml_data(self, url):
        response = requests.get(url)
        if response.status_code != 200:
            QMessageBox.warning(self, title="Error", text="Failed to retrieve XML data.")
            return

        root = ET.fromstring(response.content)
        namespaces = {'atom': 'http://www.w3.org/2005/Atom'}
        self.tableList.setRowCount(0)

        for entry in root.findall('atom:entry', namespaces):
            title = entry.find('atom:title', namespaces).text
            if title.startswith("Cadastral municipality "):
                title = title.replace("Cadastral municipality ", "").strip()
            for link in entry.findall('atom:link', namespaces):
                href = link.get('href')
                entry_id = self.get_municipality_id(href, namespaces)

            epsg, naziv_proj = self.extract_projection_info(entry, namespaces)

            current_row = self.tableList.rowCount()
            self.tableList.insertRow(current_row)
            self.tableList.setItem(current_row,0,QTableWidgetItem(title))
            self.tableList.setItem(current_row,1,QTableWidgetItem(entry_id))
            self.tableList.setItem(current_row,2,QTableWidgetItem(epsg))
            self.tableList.setItem(current_row,3,QTableWidgetItem(naziv_proj))
            self.tableList.setItem(current_row,4,QTableWidgetItem(href))

    def get_municipality_id(self, href, namespaces):
        if href.endswith(".zip"):
            entry_id_tmp = href.split('-')[-1]
            entry_id = entry_id_tmp.split('.')[0]
            return entry_id
    def extract_projection_info(self, entry, namespaces):
        for category in entry.findall('atom:category', namespaces):
            epsg = category.get("term")[-4:]
            naziv_proj = category.get("label")
        return epsg, naziv_proj

    def on_table_item_clicked(self, row, column):
        item = self.tableList.item(row, column)
        if item:
            naziv = self.tableList.item(row, 0).text()
            opcina_id = self.tableList.item(row, 1).text()
            epsg = self.tableList.item(row, 2).text()
            naziv_proj = self.tableList.item(row, 3).text()
            zip_link = self.tableList.item(row, 4).text()

            details = f"Naziv: {naziv}\nID: {opcina_id}\nEPSG: {epsg}\nNaziv projekcije: {naziv_proj}\nZip link: {zip_link}"
            self.showChosen.setText(details)

            self.selected_municipality = {
                "naziv": naziv,
                "opcina_id": opcina_id,
                "epsg": epsg,
                "naziv_proj": naziv_proj,
                "zip": zip_link
            }

    def on_list_layers_clicked(self):
        try:
            naziv = self.selected_municipality["naziv"]
            opcina_id = self.selected_municipality["opcina_id"]
            epsg = self.selected_municipality["epsg"]
            naziv_proj = self.selected_municipality["naziv_proj"]
            zip = self.selected_municipality["zip"]

            self.temp_dir = tempfile.mkdtemp()
            self.zip_path = os.path.join(self.temp_dir, naziv)
            if self.zip_path:
                QMessageBox.information(self, "Info", self.zip_path)
            response = requests.get(zip, stream=True)

            if response.status_code != 200:
                print("Failed to download the file.")
                return

            with open(self.zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=128):
                    f.write(chunk)

            with zipfile.ZipFile(self.zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.temp_dir)
                extracted_files = zip_ref.namelist()

            selected_files = self.show_checkbox_dialog(extracted_files)
            if not selected_files:
                print("No files selected.")
                return

        finally:
            #self.cleanup_directory(self.temp_dir)
            pass

    def show_checkbox_dialog(self, files):
        for file in files:
            item = QListWidgetItem(file)
            item.setCheckState(0)
            self.listWidgetFiles.addItem(item)

    def on_add_layer_clicked(self):
        if not hasattr(self, "selected_municipality"):
            QMessageBox.warning(self, title="Selection error", text="Please select a cadastral municipality first.")
            return

        selected_files = []
        for index in range(self.listWidgetFiles.count()):
            item = self.listWidgetFiles.item(index)
            if item.checkState() == 2:
                selected_files.append(item.text())

        for slct_file in selected_files:
            self.add_municipality_as_layer(slct_file)

    def add_municipality_as_layer(self, file):
        path = self.temp_dir
        file_name = path + '\\' + file
        if not file:
            QMessageBox.warning(self, "Selection error", "Please select files to add!")
            return

        layer_uri=file_name
        vector_layer = QgsVectorLayer(layer_uri, self.selected_municipality['naziv']+' '+file, "ogr")

        if not vector_layer.isValid():
            QMessageBox.critical(self, "Layer Error", "Failed to load the layer")
            return

        QgsProject.instance().addMapLayer(vector_layer)
        QMessageBox.information(self, "Layer added", "New layer added.")

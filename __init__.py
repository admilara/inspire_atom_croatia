"""
/***************************************************************************
 HR INSPIRE ATOM FEED
                                 A QGIS plugin
 Client for INSPIRE Downloadservices based on the croatian ATOM-Feed
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
 This script initializes the plugin, making it known to QGIS.
"""

import os
def classFactory(iface):
    from .croatomfeed import CroAtomFeed
    return CroAtomFeed(iface)
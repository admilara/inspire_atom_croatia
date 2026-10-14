# SPDX-License-Identifier: GPL-3.0-or-later
#
# INSPIRE ATOM Croatia – Cadastral Parcels
# QGIS plugin for downloading cadastral data from the Croatian INSPIRE ATOM feed.
#
# Copyright (C) 2024-2026 Lara Buljan <lara.buljan@outlook.com>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for details.


def classFactory(iface):  # noqa: N802 (name required by QGIS)
    from .plugin import InspireAtomCroatiaPlugin

    return InspireAtomCroatiaPlugin(iface)

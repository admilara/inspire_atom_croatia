# SPDX-License-Identifier: GPL-3.0-or-later
"""Download cache: one folder per cadastral municipality.

Layout::

    <cache root>/
        ko-305570/        extracted GML files of municipality 305570
        ko-317721/
        ...

The zip archive itself is deleted after extraction. Folders are keyed by the
municipality ID rather than the name, because several municipalities share a
name (e.g. there are two BRIBIR and two ĐURĐIC entries in the feed).

No QGIS or Qt dependencies, so this can be unit-tested with plain Python.
"""

import os
import shutil
import zipfile

VECTOR_EXTENSIONS = (".gml",)
FOLDER_PREFIX = "ko-"


class CacheError(Exception):
    pass


def normalize_dir(path, pathmod=os.path):
    """Absolute path with the platform's own separators, e.g. on Windows

        'C:/Users/x/QGIS3/profiles/default/cache\\inspire_atom_croatia'
        -> 'C:\\Users\\x\\QGIS3\\profiles\\default\\cache\\inspire_atom_croatia'

    Qt hands out paths with forward slashes on every platform, while os.path.join
    adds backslashes on Windows, so paths built from both end up mixed.
    pathmod exists so the tests can check Windows behaviour (ntpath) on any OS.
    """
    return pathmod.normpath(pathmod.abspath(pathmod.expanduser(path)))


def municipality_dir(root, municipality_id):
    return os.path.join(root, f"{FOLDER_PREFIX}{municipality_id}")


def list_vector_files(folder):
    """Relative paths of the GML files in folder (recursively), sorted."""
    found = []
    if not os.path.isdir(folder):
        return found
    for dirpath, _dirnames, filenames in os.walk(folder):
        for filename in filenames:
            if filename.lower().endswith(VECTOR_EXTENSIONS):
                full = os.path.join(dirpath, filename)
                found.append(os.path.relpath(full, folder))
    return sorted(found, key=str.lower)


def _safe_members(archive, dest):
    """Reject archive members that would be written outside dest (zip slip)."""
    dest_real = os.path.realpath(dest)
    for member in archive.infolist():
        target = os.path.realpath(os.path.join(dest, member.filename))
        if os.path.commonpath([dest_real, target]) != dest_real:
            raise CacheError(f"Unsafe path in archive: {member.filename}")
        yield member


def extract_zip(zip_path, dest, delete_zip=True):
    """Extract zip_path into dest, replacing whatever dest contained.

    Extraction goes to a sibling temporary folder first, so a corrupt
    download never leaves dest half-overwritten.
    """
    staging = dest + ".partial"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staging, members=list(_safe_members(archive, staging)))
    except zipfile.BadZipFile as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise CacheError(f"The downloaded file is not a valid zip archive ({exc}).") from exc
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.replace(staging, dest)

    if delete_zip:
        try:
            os.remove(zip_path)
        except OSError:
            pass
    return list_vector_files(dest)


def is_inside(path, folder):
    """True if path lies inside folder (both are normalised first)."""
    try:
        folder_real = os.path.normcase(os.path.realpath(folder))
        path_real = os.path.normcase(os.path.realpath(path))
        return os.path.commonpath([folder_real, path_real]) == folder_real
    except ValueError:  # different drives on Windows
        return False


def folder_size(folder):
    total = 0
    for dirpath, _dirnames, filenames in os.walk(folder):
        for filename in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, filename))
            except OSError:
                pass
    return total


def cached_folders(root):
    """Municipality folders currently in the cache root."""
    if not os.path.isdir(root):
        return []
    return sorted(
        os.path.join(root, name)
        for name in os.listdir(root)
        if name.startswith(FOLDER_PREFIX) and os.path.isdir(os.path.join(root, name))
    )


def clear_unused(root, paths_in_use):
    """Delete cached municipality folders that no path in paths_in_use points into.

    Leftover '.partial' folders from interrupted extractions are removed too.
    Returns (number of folders removed, bytes freed, folders that could not
    be removed).
    """
    removed, freed, failed = 0, 0, []
    for folder in cached_folders(root):
        if any(is_inside(p, folder) for p in paths_in_use):
            continue
        size = folder_size(folder)
        try:
            shutil.rmtree(folder)
        except OSError:
            failed.append(folder)
            continue
        if folder.endswith(".partial"):
            continue
        removed += 1
        freed += size
    return removed, freed, failed

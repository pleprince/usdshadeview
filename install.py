#!/usr/bin/env python
#
# Copyright 2025 Pablo Delgado Krämer
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for the specific language governing
# permissions and limitations under the License.
#
"""Install usdshadeview into a USD installation.

This copies the plugin into the directories that usdview/USD already
scan by default, so the plugin is picked up automatically without any
environment variables:

* ``<python path>/usdshadeview`` -> importable next to ``pxr``
* ``plugin/usd/usdshadeview``   -> registered via the install's
  ``plugin/usd/plugInfo.json`` include glob

The Python destination is taken from the directory that actually holds
the importable ``pxr`` package, so both source builds (``lib/python``)
and pip-style installs (``lib/pythonX.Y/site-packages``) work. The
plugin destination is found by walking up from there to a ``plugin/usd``
directory, or can be overridden with ``--usd-root``.

Each payload is first staged into a temporary directory next to its
destination, so a failed copy never damages an existing installation.
Every payload also receives a ``.usdshadeview.manifest`` file listing
the files it installed; subsequent installs use it to remove stale
files left behind by previous versions.

Run it with the same Python interpreter that your USD build uses::

    python install.py              # auto-detect USD root via pxr
    python install.py --usd-root /path/to/usd
    python install.py --uninstall
    python install.py -v           # also print every file operation
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import shutil
import sys
import tempfile
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("usdshadeview.install")

# Source sub-trees inside this repository and whether they are
# installed next to ``pxr`` (on the Python path) or into the plugin
# resource directory scanned by USD.
PACKAGE_NAME = "usdshadeview"
PAYLOADS = (
    (os.path.join("lib", "python", PACKAGE_NAME), "python"),
    (os.path.join("plugin", "usd", PACKAGE_NAME), "plugin"),
)

# Lists the files installed into a payload directory. Used to detect
# files that a previous install left behind and that are no longer
# part of the current one.
MANIFEST_NAME = ".usdshadeview.manifest"

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _detect_python_dir() -> str:
    """Return the directory containing the importable ``pxr`` package.

    This directory is on ``sys.path``, so placing ``usdshadeview`` next
    to ``pxr`` there guarantees that USD can import it. Works both for
    source builds (``lib/python``) and for pip-style installs
    (``lib/pythonX.Y/site-packages``).

    Returns:
        Absolute path of the directory that holds ``pxr``.

    Raises:
        RuntimeError: If ``pxr`` cannot be imported.
    """
    try:
        import pxr  # noqa: F401
    except ImportError as exc:  # pragma: no cover - env dependent
        raise RuntimeError(
            "Could not import 'pxr'. Run this script with the Python "
            "interpreter used by your USD build, or pass --usd-root."
        ) from exc

    pxr_dir = os.path.dirname(os.path.abspath(pxr.__file__))
    return os.path.dirname(pxr_dir)


def _find_pxr_under(usd_root: str) -> Optional[str]:
    """Find a ``pxr`` package directory below an explicit USD root.

    Args:
        usd_root: Absolute path to the USD installation root.

    Returns:
        Absolute path to the ``pxr`` package directory, or ``None``.

    Raises:
        RuntimeError: If several unrelated ``pxr`` packages are found.
    """
    patterns = (
        os.path.join(usd_root, "lib", "python", "pxr"),
        os.path.join(usd_root, "lib", "python*", "site-packages", "pxr"),
        os.path.join(usd_root, "lib", "python*", "pxr"),
    )
    candidates: set[str] = set()
    for pattern in patterns:
        for path in glob.glob(pattern):
            if os.path.isdir(path):
                candidates.add(os.path.abspath(path))
    if not candidates:
        return None

    try:
        import pxr  # noqa: F401

        current = os.path.dirname(os.path.abspath(pxr.__file__))
    except ImportError:
        current = None
    if current in candidates:
        return current
    if len(candidates) == 1:
        return candidates.pop()

    raise RuntimeError(
        "Found multiple 'pxr' packages under {}: {}. Remove the unused "
        "ones or run the installer with the matching interpreter.".format(
            usd_root, ", ".join(sorted(candidates))
        )
    )


def _find_plugin_dir(start: str) -> Optional[str]:
    """Find the ``plugin/usd`` directory above ``start``.

    Args:
        start: Directory to start the upward search from.

    Returns:
        Absolute path to a ``plugin/usd`` (or ``lib/usd``) directory
        that USD scans for plugin manifests, or ``None``.
    """
    current = os.path.abspath(start)
    while True:
        for name in ("plugin", "lib"):
            candidate = os.path.join(current, name, "usd")
            if os.path.isdir(candidate):
                return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def resolve_layout(usd_root: Optional[str]) -> tuple[str, str]:
    """Resolve the installation destinations.

    Args:
        usd_root: Optional explicit USD installation root.

    Returns:
        A ``(python_dir, plugin_dir)`` tuple. The Python package is
        installed into ``python_dir`` and the plugin resources into
        ``plugin_dir``.

    Raises:
        RuntimeError: If the destinations cannot be determined.
    """
    if usd_root is not None:
        usd_root = os.path.abspath(usd_root)
        if not os.path.isdir(usd_root):
            raise RuntimeError(
                "USD root does not exist: {}".format(usd_root)
            )
        pxr_dir = _find_pxr_under(usd_root)
        if pxr_dir is None:
            raise RuntimeError(
                "Could not find a 'pxr' package under {}. Pass "
                "--usd-root pointing at a USD installation.".format(
                    usd_root
                )
            )
        return (
            os.path.dirname(pxr_dir),
            os.path.join(usd_root, "plugin", "usd"),
        )

    python_dir = _detect_python_dir()
    plugin_dir = _find_plugin_dir(python_dir)
    if plugin_dir is None:
        raise RuntimeError(
            "Could not locate a USD 'plugin/usd' directory above {}. "
            "Pass --usd-root.".format(python_dir)
        )
    return python_dir, plugin_dir


def _manifest_path(dest: str) -> str:
    """Return the manifest path inside a payload directory."""
    return os.path.join(dest, MANIFEST_NAME)


def _normalize_rel(rel: str) -> str:
    """Convert a relative path to forward-slash form."""
    return rel.replace(os.sep, "/")


def _join_rel(root: str, rel: str) -> str:
    """Join a forward-slash relative path onto ``root``."""
    return os.path.join(root, *rel.split("/"))


def _safe_join(root: str, rel: str) -> Optional[str]:
    """Join ``rel`` onto ``root``, rejecting paths that escape it.

    Args:
        root: Directory that must contain the result.
        rel: Forward-slash relative path.

    Returns:
        The joined path, or ``None`` if ``rel`` is absolute, empty,
        or contains parent-directory components.
    """
    parts = rel.split("/")
    if not rel or os.path.isabs(rel):
        return None
    if any(part in ("", "..") for part in parts):
        return None
    full = os.path.abspath(os.path.join(root, *parts))
    root_abs = os.path.abspath(root)
    try:
        if os.path.commonpath([root_abs, full]) != root_abs:
            return None
    except ValueError:  # Different drives on Windows.
        return None
    return full


def _collect_files(root: str) -> set[str]:
    """Return all files under ``root`` as normalized relative paths."""
    files: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            files.add(_normalize_rel(os.path.relpath(full, root)))
    return files


def _read_manifest(dest: str) -> Optional[set[str]]:
    """Read the manifest of a payload directory.

    Returns:
        The set of recorded relative paths, or ``None`` if no manifest
        exists (e.g. for a legacy or manual installation).
    """
    path = _manifest_path(dest)
    if not os.path.isfile(path):
        return None
    entries: set[str] = set()
    with open(path, "r", encoding="utf-8") as manifest:
        for line in manifest:
            rel = line.strip()
            if rel:
                entries.add(rel)
    return entries


def _write_manifest(dest: str, files: set[str]) -> None:
    """Atomically write the manifest for a payload directory."""
    os.makedirs(dest, exist_ok=True)
    path = _manifest_path(dest)
    tmp_path = path + ".tmp"
    logger.debug("write manifest %s (%d entries)", path, len(files))
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as manifest:
        for rel in sorted(files):
            manifest.write(rel + "\n")
    os.replace(tmp_path, path)


def _stage_payload(src: str, dst: str) -> tuple[str, str]:
    """Copy ``src`` into a temporary staging directory next to ``dst``.

    Args:
        src: Source directory to copy.
        dst: Final destination directory.

    Returns:
        A ``(staging_root, staged_payload)`` tuple. The caller must
        remove ``staging_root`` when done.
    """
    parent = os.path.dirname(dst)
    os.makedirs(parent, exist_ok=True)
    staging_root = tempfile.mkdtemp(prefix=".usdshadeview-tmp-", dir=parent)
    staged = os.path.join(staging_root, "payload")
    logger.debug("create staging dir %s", staging_root)
    try:
        shutil.copytree(src, staged)
    except (OSError, shutil.Error):
        logger.debug("discard staging dir %s", staging_root)
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    for rel in sorted(_collect_files(staged)):
        logger.debug("stage %s", rel)
    return staging_root, staged


def _merge_copy(src: str, dst: str) -> None:
    """Copy files from ``src`` into ``dst``, overwriting existing ones."""
    for rel in sorted(_collect_files(src)):
        src_path = _join_rel(src, rel)
        dst_path = _safe_join(dst, rel)
        if dst_path is None:
            raise RuntimeError(
                "Refusing to write outside destination: {}".format(rel)
            )
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        logger.debug("copy %s -> %s", src_path, dst_path)
        shutil.copy2(src_path, dst_path)


def _prune_empty_dirs(root: str) -> None:
    """Remove empty directories below ``root`` (never ``root``)."""
    root_abs = os.path.abspath(root)
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        if os.path.abspath(dirpath) == root_abs:
            continue
        try:
            os.rmdir(dirpath)
            logger.debug("remove empty dir %s", dirpath)
        except OSError:
            pass


def _remove_stale(dst: str, stale: set[str]) -> None:
    """Delete files that a previous install left behind."""
    for rel in sorted(stale):
        path = _safe_join(dst, rel)
        if path is None:
            continue
        if os.path.islink(path) or os.path.isfile(path):
            logger.debug("remove stale file %s", path)
            os.remove(path)
    _prune_empty_dirs(dst)


def _remove_legacy_python_dir(layout: tuple[str, str]) -> None:
    """Remove a package left at ``<root>/lib/python`` by old versions.

    Older installers assumed every USD build kept ``pxr`` directly in
    ``<root>/lib/python``. On pip-style installs the real Python path is
    ``<root>/lib/pythonX.Y/site-packages``, leaving the old package in a
    directory that is not importable. Remove it once the correct
    destination is known.
    """
    python_dir, plugin_dir = layout
    if os.path.basename(plugin_dir) != "usd" or os.path.basename(
        os.path.dirname(plugin_dir)
    ) != "plugin":
        return
    root = os.path.dirname(os.path.dirname(plugin_dir))
    legacy = os.path.join(root, "lib", "python", PACKAGE_NAME)
    target = os.path.join(python_dir, PACKAGE_NAME)
    if os.path.abspath(legacy) == os.path.abspath(target):
        return
    if os.path.islink(legacy) or os.path.isfile(legacy):
        logger.info("Removed legacy install %s", legacy)
        os.remove(legacy)
    elif os.path.isdir(legacy):
        logger.info("Removed legacy install %s", legacy)
        shutil.rmtree(legacy)


def install(layout: tuple[str, str]) -> None:
    """Install all payloads.

    Args:
        layout: ``(python_dir, plugin_dir)`` destinations.
    """
    python_dir, plugin_dir = layout
    targets = {"python": python_dir, "plugin": plugin_dir}
    for src_rel, kind in PAYLOADS:
        src = os.path.join(REPO_ROOT, src_rel)
        dst = os.path.join(targets[kind], PACKAGE_NAME)
        if not os.path.isdir(src):
            raise RuntimeError("Missing source directory: {}".format(src))

        staging_root, staged = _stage_payload(src, dst)
        try:
            if os.path.islink(dst) or (
                os.path.exists(dst) and not os.path.isdir(dst)
            ):
                logger.debug("remove non-directory destination %s", dst)
                os.remove(dst)

            new_files = _collect_files(staged)
            old_files = _read_manifest(dst)
            if old_files is None:
                # No manifest: assume everything present belongs to a
                # legacy install so that nothing stale survives.
                old_files = (
                    _collect_files(dst) if os.path.isdir(dst) else set()
                )
                old_files.discard(MANIFEST_NAME)
                logger.debug(
                    "no manifest; treating %d existing file(s) as stale",
                    len(old_files),
                )

            # Copy first so a failure leaves the previous install
            # intact, then drop files that are no longer shipped.
            _merge_copy(staged, dst)
            _remove_stale(dst, old_files - new_files)
            _write_manifest(dst, new_files)
        finally:
            logger.debug("discard staging dir %s", staging_root)
            shutil.rmtree(staging_root, ignore_errors=True)

        logger.info("Installed %s -> %s", src_rel, dst)

    _remove_legacy_python_dir(layout)


def uninstall(layout: tuple[str, str]) -> None:
    """Remove all previously installed payloads.

    Args:
        layout: ``(python_dir, plugin_dir)`` destinations.
    """
    python_dir, plugin_dir = layout
    targets = {"python": python_dir, "plugin": plugin_dir}
    for _src_rel, kind in PAYLOADS:
        dst = os.path.join(targets[kind], PACKAGE_NAME)
        if os.path.islink(dst) or os.path.exists(dst):
            if os.path.islink(dst) or os.path.isfile(dst):
                logger.debug("remove file %s", dst)
                os.remove(dst)
            else:
                logger.debug("remove directory %s", dst)
                shutil.rmtree(dst)
            logger.info("Removed %s", dst)
        else:
            logger.info("Not present, skipping %s", dst)

    _remove_legacy_python_dir(layout)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Install usdshadeview into a USD installation."
    )
    parser.add_argument(
        "--usd-root",
        default=None,
        help="USD installation root. Defaults to auto-detecting the "
        "importable 'pxr' package and a 'plugin/usd' directory above it.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove a previously installed usdshadeview.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print every file operation.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Entry point.

    Args:
        argv: Command line arguments (excluding the program name).

    Returns:
        Process exit code.
    """
    args = parse_args(argv)
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    try:
        layout = resolve_layout(args.usd_root)
        logger.info("Python dir: %s", layout[0])
        logger.info("Plugin dir: %s", layout[1])
        if args.uninstall:
            uninstall(layout)
            logger.info("Uninstall complete.")
        else:
            install(layout)
            logger.info(
                "Install complete. Launch usdview; the plugin loads "
                "automatically."
            )
    except (RuntimeError, OSError, shutil.Error) as exc:
        logger.error("Error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Inspecting a built distribution against an allowlist.

Packaging is its own way to publish a private file. A source tree that scans
clean says nothing about what the build backend swept into the sdist, and a
`prune` that stops working is silent: the artifact simply gets bigger.

So the members of a distribution are checked against an allowlist rather than
a denylist. A wheel is small and completely enumerable, which makes
"is every member something we meant to ship" a question that can actually be
answered - and unlike a denylist, it catches the file nobody thought of.
"""

import hashlib
import os
import re
import tarfile
import zipfile


class ArtifactError(Exception):
    """The artifact could not be read as the kind of artifact it claims to be."""


#: Wheel members AIQE ships. `aiqe/<module>.py` and the distribution metadata,
#: and nothing else: there is no package data, no bundled binary and no
#: bundled configuration in this project, so a member outside these shapes is
#: either a mistake or something that should never have been in the tree.
WHEEL_ALLOWED = (
    re.compile(r"^aiqe/[A-Za-z_][A-Za-z0-9_]*\.py$"),
    re.compile(r"^aiqe-[^/]+\.dist-info/(METADATA|RECORD|WHEEL|entry_points\.txt|top_level\.txt)$"),
    re.compile(r"^aiqe-[^/]+\.dist-info/licenses/LICENSE$"),
)

#: Sdist members AIQE ships, relative to the single top-level directory every
#: sdist has. `src/aiqe.egg-info/` is setuptools' own build metadata: it is
#: generated, it is in every setuptools sdist on any index, and it is listed
#: here explicitly rather than tolerated by an exception.
SDIST_ALLOWED = (
    re.compile(r"^(LICENSE|MANIFEST\.in|PKG-INFO|README\.md|pyproject\.toml|setup\.cfg)$"),
    re.compile(r"^src/aiqe/[A-Za-z_][A-Za-z0-9_]*\.py$"),
    re.compile(
        r"^src/aiqe\.egg-info/"
        r"(PKG-INFO|SOURCES\.txt|dependency_links\.txt|entry_points\.txt|top_level\.txt)$"
    ),
)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _disallowed(members, allowed):
    return sorted(
        member
        for member in members
        if not any(pattern.match(member) for pattern in allowed)
    )


def _parse_metadata(text):
    """Parse the RFC 822 header block of a METADATA/PKG-INFO file.

    Only the headers. The body is the README, and it is not metadata.
    """
    headers = {}
    for line in text.splitlines():
        if not line.strip():
            break
        if line[:1] in (" ", "\t"):
            continue
        key, _, value = line.partition(":")
        headers.setdefault(key.strip(), []).append(value.strip())
    return headers


def inspect_wheel(path):
    """Everything the release proof needs to know about a wheel."""
    if not zipfile.is_zipfile(path):
        raise ArtifactError("%s is not a zip archive" % (path,))
    with zipfile.ZipFile(path) as archive:
        members = sorted(name for name in archive.namelist() if not name.endswith("/"))
        dist_info = [name for name in members if ".dist-info/METADATA" in name]
        if not dist_info:
            raise ArtifactError("%s has no dist-info METADATA" % (path,))
        metadata = _parse_metadata(
            archive.read(dist_info[0]).decode("utf-8", "replace")
        )
        wheel_headers = _parse_metadata(
            archive.read(dist_info[0].replace("METADATA", "WHEEL")).decode(
                "utf-8", "replace"
            )
        )
        entry_points = ""
        entry_point_name = dist_info[0].replace("METADATA", "entry_points.txt")
        if entry_point_name in members:
            entry_points = archive.read(entry_point_name).decode("utf-8", "replace")
        licenses = [name for name in members if "/licenses/" in name]

    console_scripts = {}
    section = None
    for line in entry_points.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        if section == "console_scripts" and "=" in stripped:
            name, _, target = stripped.partition("=")
            console_scripts[name.strip()] = target.strip()

    return {
        "filename": os.path.basename(path),
        "sha256": sha256(path),
        "size_bytes": os.path.getsize(path),
        "members": members,
        "disallowed_members": _disallowed(members, WHEEL_ALLOWED),
        "name": (metadata.get("Name") or [None])[0],
        "version": (metadata.get("Version") or [None])[0],
        "requires_python": (metadata.get("Requires-Python") or [None])[0],
        "requires_dist": metadata.get("Requires-Dist", []),
        "license": (metadata.get("License") or [None])[0],
        "license_files": sorted(licenses),
        "classifiers": metadata.get("Classifier", []),
        "description_content_type": (
            metadata.get("Description-Content-Type") or [None]
        )[0],
        "wheel_tags": wheel_headers.get("Tag", []),
        "root_is_purelib": (wheel_headers.get("Root-Is-Purelib") or [None])[0],
        "generator": (wheel_headers.get("Generator") or [None])[0],
        "console_scripts": console_scripts,
    }


def inspect_sdist(path):
    """Everything the release proof needs to know about a source distribution."""
    try:
        archive = tarfile.open(path, "r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise ArtifactError("%s is not a gzipped tar archive: %s" % (path, exc))
    with archive:
        names = archive.getnames()
        files = sorted(
            member.name for member in archive.getmembers() if member.isfile()
        )
        roots = {name.split("/")[0] for name in names if name}
        if len(roots) != 1:
            raise ArtifactError(
                "%s has %d top-level entries, expected exactly 1" % (path, len(roots))
            )
        root = roots.pop()
        relative = sorted(
            name[len(root) + 1 :] for name in files if name.startswith(root + "/")
        )
        pkg_info_name = "%s/PKG-INFO" % (root,)
        if pkg_info_name not in files:
            raise ArtifactError("%s has no PKG-INFO" % (path,))
        extracted = archive.extractfile(pkg_info_name)
        metadata = _parse_metadata(extracted.read().decode("utf-8", "replace"))

    return {
        "filename": os.path.basename(path),
        "sha256": sha256(path),
        "size_bytes": os.path.getsize(path),
        "root": root,
        "members": relative,
        "disallowed_members": _disallowed(relative, SDIST_ALLOWED),
        "name": (metadata.get("Name") or [None])[0],
        "version": (metadata.get("Version") or [None])[0],
        "requires_python": (metadata.get("Requires-Python") or [None])[0],
        "requires_dist": metadata.get("Requires-Dist", []),
        "license": (metadata.get("License") or [None])[0],
        "classifiers": metadata.get("Classifier", []),
    }


def extract_wheel(path, destination):
    with zipfile.ZipFile(path) as archive:
        archive.extractall(destination)
    return destination


def extract_sdist(path, destination):
    with tarfile.open(path, "r:gz") as archive:
        try:
            archive.extractall(destination, filter="data")
        except TypeError:  # pragma: no cover - Python without the filter argument
            archive.extractall(destination)
    return destination


def _wheel_entries(path):
    with zipfile.ZipFile(path) as archive:
        return {
            info.filename: archive.read(info.filename)
            for info in archive.infolist()
            if not info.is_dir()
        }, {
            info.filename: {"date_time": info.date_time, "mode": info.external_attr >> 16}
            for info in archive.infolist()
        }


def _sdist_entries(path):
    with tarfile.open(path, "r:gz") as archive:
        content = {}
        metadata = {}
        for member in archive.getmembers():
            metadata[member.name] = {
                "mtime": member.mtime,
                "mode": member.mode,
                "uid": member.uid,
                "gid": member.gid,
                "uname": member.uname,
                "gname": member.gname,
                "type": member.type.decode("ascii", "replace")
                if isinstance(member.type, bytes)
                else str(member.type),
            }
            if member.isfile():
                extracted = archive.extractfile(member)
                content[member.name] = extracted.read() if extracted else b""
    return content, metadata


def compare_builds(first, second):
    """Decompose the difference between two builds of the same source.

    Two artifacts can differ in two very different ways, and collapsing them
    into one boolean is how a project ends up either claiming reproducible
    builds it does not have or reporting a scary red flag for a timestamp.

    So the comparison answers both questions separately: is every packaged
    file byte-identical, and if the archives still differ, which archive
    metadata fields differ. The first is an integrity question. The second is
    a build-procedure question.
    """
    if first.endswith(".whl"):
        first_content, first_meta = _wheel_entries(first)
        second_content, second_meta = _wheel_entries(second)
    else:
        first_content, first_meta = _sdist_entries(first)
        second_content, second_meta = _sdist_entries(second)

    identical_bytes = sha256(first) == sha256(second)
    same_member_set = set(first_content) == set(second_content)
    differing_content = sorted(
        name
        for name in set(first_content) & set(second_content)
        if first_content[name] != second_content[name]
    )
    differing_fields = {}
    for name in sorted(set(first_meta) & set(second_meta)):
        for field, value in first_meta[name].items():
            if second_meta[name].get(field) != value:
                differing_fields.setdefault(field, []).append(name)

    return {
        "identical_bytes": identical_bytes,
        "same_member_set": same_member_set,
        "members_only_in_first": sorted(set(first_content) - set(second_content)),
        "members_only_in_second": sorted(set(second_content) - set(first_content)),
        "members_with_differing_content": differing_content,
        "content_identical": same_member_set and not differing_content,
        "differing_metadata_fields": {
            field: sorted(names) for field, names in sorted(differing_fields.items())
        },
    }

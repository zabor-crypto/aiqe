"""Static, bounded reader for Git configuration files.

Doctor reads configuration files as text. It does not ask Git to resolve
configuration, and it does not follow `include` or `includeIf`.

That is a deliberate boundary, not an implementation shortcut. Asking Git for
a value resolves the whole configuration chain, so an `include.path` pointing
anywhere on the filesystem silently becomes part of the answer. Doctor is
first-contact inspection: it runs before the user has told AIQE anything, and
it must not present a value pulled out of an unresolved chain as though it
were established fact. When an include directive is present, Doctor reports
that the effective configuration is unresolved and stops there.

Resolving effective configuration is a higher-authority operation that belongs
to commit preflight, which must either resolve it unambiguously or refuse.
Nothing in this module is that operation, and nothing here should grow into
it.

The parser accepts the documented Git configuration file syntax: section
headers with optional subsections, `key = value` pairs, a bare key meaning
true, `#` and `;` comments, quoted values, backslash escapes and line
continuations. It is used only to answer presence questions, so where the
syntax is ambiguous it fails towards "unreadable", which Doctor reports as an
unknown.
"""

import io

#: Characters escapable inside a configuration value.
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "b": "\b",
    "\\": "\\",
    '"': '"',
}


class ConfigError(Exception):
    """The file could not be parsed as Git configuration."""


class ConfigFile(object):
    """The parsed contents of a single Git configuration file.

    `entries` is a list of (section, subsection, key, value) tuples in file
    order. `section` and `key` are lowercased, as Git treats them
    case-insensitively. `subsection` keeps its case, as Git does. `value` is
    None for a bare key.
    """

    __slots__ = ("path", "entries")

    def __init__(self, path, entries):
        self.path = path
        self.entries = entries

    def has_section(self, section):
        section = section.lower()
        return any(entry[0] == section for entry in self.entries)

    def get(self, section, key):
        """Last value for a dotted two-part name, or None.

        Git's last-one-wins rule applies within a file.
        """
        section = section.lower()
        key = key.lower()
        found = None
        for entry_section, _subsection, entry_key, value in self.entries:
            if entry_section == section and entry_key == key:
                found = value
        return found

    def subsection_keys(self, section, key):
        """Subsections of `section` that define `key`.

        Answers questions of the shape "which filter drivers define a clean
        command", without needing to know the driver names in advance.
        """
        section = section.lower()
        key = key.lower()
        out = []
        for entry_section, subsection, entry_key, _value in self.entries:
            if entry_section == section and entry_key == key and subsection is not None:
                if subsection not in out:
                    out.append(subsection)
        return out

    def keys_in(self, section):
        """All (key, value) pairs in `section`, in file order."""
        section = section.lower()
        return [
            (entry_key, value)
            for entry_section, _subsection, entry_key, value in self.entries
            if entry_section == section
        ]


def is_true(value):
    """Git's boolean reading of a configuration value.

    A bare key with no value is true. Otherwise Git accepts a small set of
    literals; anything else is not a boolean and is not treated as true.
    """
    if value is None:
        return True
    return value.strip().lower() in ("true", "yes", "on", "1")


def parse_text(text, path=None):
    """Parse Git configuration text. Raises ConfigError on malformed input."""
    entries = []
    section = None
    subsection = None

    stream = io.StringIO(text)
    pending = ""
    for raw_line in stream:
        line = raw_line.rstrip("\n").rstrip("\r")
        if pending:
            line = pending + line
            pending = ""
        # A trailing backslash continues the logical line.
        if line.endswith("\\") and not line.endswith("\\\\"):
            pending = line[:-1]
            continue

        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            continue

        if stripped[0] == "[":
            section, subsection = _parse_header(stripped, path)
            continue

        if section is None:
            raise ConfigError("key outside any section in %r" % (path,))

        key, value = _parse_key_value(stripped, path)
        entries.append((section, subsection, key, value))

    if pending.strip():
        raise ConfigError("unterminated line continuation in %r" % (path,))

    return ConfigFile(path, entries)


def _parse_header(text, path):
    end = text.find("]")
    if end == -1:
        raise ConfigError("unterminated section header in %r" % (path,))
    inner = text[1:end].strip()
    if not inner:
        raise ConfigError("empty section header in %r" % (path,))

    if '"' in inner:
        # [section "subsection"]
        name, _, rest = inner.partition(" ")
        rest = rest.strip()
        if not (rest.startswith('"') and rest.endswith('"') and len(rest) >= 2):
            raise ConfigError("malformed subsection in %r" % (path,))
        return name.strip().lower(), _unescape_subsection(rest[1:-1])

    if "." in inner:
        # Legacy [section.subsection] form.
        name, _, sub = inner.partition(".")
        return name.strip().lower(), sub.strip()

    return inner.lower(), None


def _unescape_subsection(text):
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            index += 1
            out.append(text[index])
        else:
            out.append(char)
        index += 1
    return "".join(out)


def _parse_key_value(text, path):
    equals = text.find("=")
    if equals == -1:
        key = _strip_inline_comment(text).strip()
        if not key:
            raise ConfigError("empty key in %r" % (path,))
        return key.lower(), None

    key = text[:equals].strip().lower()
    if not key:
        raise ConfigError("empty key in %r" % (path,))
    return key, _parse_value(text[equals + 1:])


def _parse_value(text):
    out = []
    in_quotes = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            index += 1
            out.append(_ESCAPES.get(text[index], text[index]))
        elif char == '"':
            in_quotes = not in_quotes
        elif char in "#;" and not in_quotes:
            break
        else:
            out.append(char)
        index += 1
    return "".join(out).strip()


def _strip_inline_comment(text):
    for marker in ("#", ";"):
        position = text.find(marker)
        if position != -1:
            text = text[:position]
    return text


def read_file(path):
    """Parse a configuration file from disk.

    Returns None when the file does not exist - an absent file is a fact, not
    a failure. Raises ConfigError when the file exists but cannot be read or
    parsed, which Doctor turns into an unknown rather than an assumed absence.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigError("cannot read %r: %s" % (path, exc))

    return parse_text(raw.decode("utf-8", "replace"), path=path)

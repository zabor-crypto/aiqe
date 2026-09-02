"""Rendering user-controlled bytes into a terminal without lying to it.

Owned paths and task labels come from the user, and a repository can contain a
filename with a newline, an escape character, or bytes that are not text at
all. Printed literally, such a name can move the cursor, colour the output, or
draw a line that looks like another status row. A tool whose whole claim is
that it tells you exactly what is in scope must not be the thing that fakes a
row.

So display is escaped, and the stored value is not touched. What AIQE records
is the exact bytes; what it prints is a rendering of them. The two must not be
confused, which is why the escaping lives here rather than in the state layer.

The escaping is the familiar one - `\\n`, `\\t`, `\\xNN` - chosen because it is
unambiguous and reversible by eye, not because it is pretty. A backslash in a
real filename is doubled so that an escape and a literal cannot be mistaken
for one another.
"""

#: Control characters get named escapes where a name exists.
_NAMED = {
    0x09: "\\t",
    0x0A: "\\n",
    0x0D: "\\r",
}


def display_bytes(raw):
    """Render raw path bytes as a single safe line of text.

    Bytes that are not valid UTF-8 survive as `\\xNN`: they are part of the
    path's identity, and hiding them behind a replacement character would make
    two different paths render identically.
    """
    return display_text(raw.decode("utf-8", "surrogateescape"))


def display_text(text):
    """Render a string - possibly carrying surrogateescape bytes - safely."""
    out = []
    for character in text:
        code = ord(character)
        if 0xDC80 <= code <= 0xDCFF:
            # A byte that was not valid UTF-8, preserved by surrogateescape.
            out.append("\\x%02x" % (code - 0xDC00,))
        elif character == "\\":
            out.append("\\\\")
        elif code in _NAMED:
            out.append(_NAMED[code])
        elif code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            # C0 and C1 control characters, including ESC. These are what
            # would otherwise let a filename repaint the terminal.
            out.append("\\x%02x" % (code,))
        else:
            out.append(character)
    return "".join(out)


def is_safe(rendered):
    """True when a rendered string carries no control characters at all.

    Used by the tests to assert the property directly rather than by
    inspecting the escaping rules.
    """
    for character in rendered:
        code = ord(character)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F or code >= 0xD800 and code <= 0xDFFF:
            return False
    return True

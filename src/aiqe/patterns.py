"""The AIQE surface pattern grammar.

A `[[surface]]` declaration names paths with patterns, and those patterns are
AIQE's own. They are never handed to Git, and they are not Git pathspec
syntax: Git pathspec carries magic prefixes, `:(glob)`, `:(icase)`, exclusion
and attribute selectors, and their meanings depend on Git's version and
configuration. A classification rule that decides which contracts apply to a
change cannot rest on a syntax whose meaning is negotiable.

So the grammar is small, written out, and matched here:

```
literal bytes   match themselves
*               zero or more bytes, within one path component
?               exactly one byte, within one path component
**              an entire component: zero or more whole path components
[...]           a byte class, within one path component
```

`[...]` follows the POSIX shell conventions and nothing more: a leading `!`
or `^` negates, `a-z` is an inclusive byte range, and a `]` immediately after
the opening bracket (or after the negation) is a literal `]`. There is no
backslash escape, no character-class name, and no collating element. A
pattern that opens a class and never closes it is a configuration error, not
a literal bracket.

Two properties are load-bearing.

**Matching is on bytes.** A repository path is a byte string, and decoding one
to classify it would give a repository with an unusual filename a different
answer - or an exception - from the component that decides which quant
contracts apply to it. Pattern text arrives from TOML, which is UTF-8 by
definition, and is encoded once at compile time. After that the matcher never
sees text.

**`**` is a component, not a wildcard.** `src/**` matches `src`, `src/a` and
`src/a/b`; `a**b` is refused rather than quietly treated as `a*b`, because a
pattern whose author expected recursion and got one component's worth of
matching is a classification gap nobody sees.

Compilation refuses anything ambiguous rather than interpreting it: an empty
pattern, an absolute pattern, a trailing separator, an empty or `.` or `..`
component, a NUL byte, `**` sharing a component with anything else, and an
unterminated byte class.
"""

SEPARATOR = b"/"

#: Token kinds inside one compiled component.
_LITERAL = "literal"
_STAR = "star"
_ANY = "any"
_CLASS = "class"

#: The whole-component recursion token.
_GLOBSTAR = "globstar"


class PatternError(Exception):
    """A surface pattern AIQE will not interpret.

    `code` is the stable machine identity; the message names the pattern and
    says what is wrong with it.
    """

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


PATTERN_EMPTY = "SURFACE_PATTERN_EMPTY"
PATTERN_ABSOLUTE = "SURFACE_PATTERN_ABSOLUTE"
PATTERN_COMPONENT_EMPTY = "SURFACE_PATTERN_COMPONENT_EMPTY"
PATTERN_COMPONENT_RELATIVE = "SURFACE_PATTERN_COMPONENT_RELATIVE"
PATTERN_GLOBSTAR_NOT_A_COMPONENT = "SURFACE_PATTERN_GLOBSTAR_NOT_A_COMPONENT"
PATTERN_CLASS_UNTERMINATED = "SURFACE_PATTERN_CLASS_UNTERMINATED"
PATTERN_CLASS_EMPTY = "SURFACE_PATTERN_CLASS_EMPTY"
PATTERN_NUL_BYTE = "SURFACE_PATTERN_NUL_BYTE"


class Pattern(object):
    """One compiled surface pattern.

    `source` is the pattern as written, kept for messages and for the config
    digest's benefit. `components` is the compiled form the matcher walks.
    """

    __slots__ = ("source", "components")

    def __init__(self, source, components):
        self.source = source
        self.components = components

    def matches(self, path):
        """Does this pattern match a repository-relative path, as bytes?"""
        if not isinstance(path, bytes):
            raise TypeError("a repository path is matched as bytes")
        return _match_components(
            self.components, path.split(SEPARATOR), 0, 0, {}
        )

    def __repr__(self):
        return "Pattern(%r)" % (self.source,)


def compile_pattern(text):
    """Compile one pattern from its TOML text. Raises `PatternError`.

    `text` is a string, because TOML is UTF-8 text. It is encoded once here;
    everything after this point is bytes.
    """
    if isinstance(text, bytes):
        raw = text
    else:
        raw = text.encode("utf-8", "surrogateescape")

    if not raw:
        raise PatternError(PATTERN_EMPTY, "a surface pattern may not be empty")
    if b"\0" in raw:
        raise PatternError(
            PATTERN_NUL_BYTE, "a surface pattern may not contain a NUL byte"
        )
    if raw.startswith(SEPARATOR):
        raise PatternError(
            PATTERN_ABSOLUTE,
            "a surface pattern is relative to the repository root; %s starts "
            "with a separator" % (_render(raw),),
        )

    components = []
    for component in raw.split(SEPARATOR):
        if component == b"":
            raise PatternError(
                PATTERN_COMPONENT_EMPTY,
                "a surface pattern may not contain an empty component or a "
                "trailing separator; %s does" % (_render(raw),),
            )
        if component in (b".", b".."):
            raise PatternError(
                PATTERN_COMPONENT_RELATIVE,
                "a surface pattern is already relative to the repository "
                "root, so %s has no meaning in %s"
                % (_render(component), _render(raw)),
            )
        if component == b"**":
            components.append((_GLOBSTAR,))
            continue
        if b"**" in component:
            raise PatternError(
                PATTERN_GLOBSTAR_NOT_A_COMPONENT,
                "** matches whole path components, so it must be a component "
                "of its own; %s in %s does not say what its author meant"
                % (_render(component), _render(raw)),
            )
        components.append(_compile_component(component, raw))

    return Pattern(raw, tuple(components))


def _compile_component(component, whole):
    """Compile one component into a token tuple."""
    tokens = []
    literal = bytearray()
    index = 0
    length = len(component)

    while index < length:
        byte = component[index:index + 1]
        if byte == b"*":
            if literal:
                tokens.append((_LITERAL, bytes(literal)))
                literal = bytearray()
            tokens.append((_STAR,))
            index += 1
            continue
        if byte == b"?":
            if literal:
                tokens.append((_LITERAL, bytes(literal)))
                literal = bytearray()
            tokens.append((_ANY,))
            index += 1
            continue
        if byte == b"[":
            if literal:
                tokens.append((_LITERAL, bytes(literal)))
                literal = bytearray()
            token, index = _compile_class(component, index, whole)
            tokens.append(token)
            continue
        literal += component[index:index + 1]
        index += 1

    if literal:
        tokens.append((_LITERAL, bytes(literal)))
    return tuple(tokens)


def _compile_class(component, start, whole):
    """Compile `[...]` beginning at `start`. Returns (token, next index)."""
    index = start + 1
    negated = False
    if component[index:index + 1] in (b"!", b"^"):
        negated = True
        index += 1

    members = set()
    ranges = []
    first = True

    while index < len(component):
        byte = component[index]
        char = component[index:index + 1]
        if char == b"]" and not first:
            token = (_CLASS, negated, frozenset(members), tuple(ranges))
            return token, index + 1
        first = False

        # `a-z`, but a trailing `-` before the closing bracket is a literal.
        if (
            component[index + 1:index + 2] == b"-"
            and component[index + 2:index + 3] not in (b"", b"]")
        ):
            ranges.append((byte, component[index + 2]))
            index += 3
            continue

        members.add(byte)
        index += 1

    raise PatternError(
        PATTERN_CLASS_UNTERMINATED,
        "a byte class opened with [ is never closed in %s" % (_render(whole),),
    )


def _match_components(components, path_components, index, position, memo):
    """Match compiled components against path components.

    `**` is the only place this branches, and the memo bounds the branching:
    each (component index, path position) pair is decided once, so a pattern
    with several `**` components cannot make matching blow up.
    """
    key = (index, position)
    cached = memo.get(key)
    if cached is not None:
        return cached

    result = _match_components_uncached(
        components, path_components, index, position, memo
    )
    memo[key] = result
    return result


def _match_components_uncached(components, path_components, index, position, memo):
    if index == len(components):
        return position == len(path_components)

    component = components[index]
    if component[0] == _GLOBSTAR:
        # Zero or more whole components, including zero.
        for consumed in range(position, len(path_components) + 1):
            if _match_components(
                components, path_components, index + 1, consumed, memo
            ):
                return True
        return False

    if position == len(path_components):
        return False
    if not _match_tokens(component, path_components[position]):
        return False
    return _match_components(
        components, path_components, index + 1, position + 1, memo
    )


def _match_tokens(tokens, segment):
    """Match one compiled component against one path component's bytes.

    A frontier of reachable offsets rather than recursion: `*` can only ever
    move the frontier forward, so one pass over the tokens decides the
    component and no input can make it backtrack.
    """
    reachable = {0}
    length = len(segment)

    for token in tokens:
        if not reachable:
            return False
        kind = token[0]

        if kind == _LITERAL:
            text = token[1]
            size = len(text)
            reachable = {
                offset + size
                for offset in reachable
                if segment[offset:offset + size] == text
            }
        elif kind == _STAR:
            # Everything from the earliest reachable offset to the end.
            reachable = set(range(min(reachable), length + 1))
        elif kind == _ANY:
            reachable = {offset + 1 for offset in reachable if offset < length}
        else:
            _, negated, members, ranges = token
            reachable = {
                offset + 1
                for offset in reachable
                if offset < length
                and _in_class(segment[offset], negated, members, ranges)
            }

    return length in reachable


def _in_class(byte, negated, members, ranges):
    inside = byte in members
    if not inside:
        for low, high in ranges:
            if low <= byte <= high:
                inside = True
                break
    return (not inside) if negated else inside


def _render(raw):
    from .textsafe import display_bytes

    return display_bytes(raw)

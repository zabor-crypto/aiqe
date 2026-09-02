"""`./aiqe.toml`: the repository's declaration of what it has and what checks it.

Two block types, and no others:

```toml
schema = 1

[[surface]]
paths = ["src/strategy/**"]
quant = true
contracts = ["CAUSALITY", "DATA_ALIGNMENT"]

[[validator]]
id = "causality"
run = ["python", "checks/no_lookahead.py"]
required = true
timeout = 120
contracts = ["CAUSALITY"]
```

Parsing is **fail-closed**, and that is the whole design. Every other
configuration reader in a developer's day is permissive: unknown keys are
ignored, missing values get defaults, a typo is silently something else. That
is a reasonable trade when the cost of a misread key is a mildly wrong colour
scheme. Here the cost is a quant surface that classifies as ordinary code, or
a required validator that silently became optional, and either one produces a
green result that means nothing.

So an unknown key is an error. A missing `quant` is an error rather than
`false`. A missing `timeout` is an error rather than "wait forever". A
duplicate validator id is an error rather than last-one-wins. Every refusal
exits 3 - `UNSUPPORTED`, the code that means AIQE will not proceed - and names
the block and field it refused.

**The file is executable trust material, not authorization.** A `[[validator]]`
declaration is tracked content: anyone who can land a commit can write one,
and it names a command AIQE would otherwise run as the user. Nothing in this
module decides to execute anything. Consent is separate, machine-local, and
bound to a validator's semantic definition digest - see `validators.py`.

The configuration digest is taken over the file's **raw bytes**, not over the
parsed structure. A digest of the parsed form would be stable across an edit
that changed a comment explaining why a validator is required, and staleness
detection is more useful when it is conservative: if the file a check ran
against is not byte-identical to the file now on disk, the evidence is not
described by the file the user is reading.
"""

import hashlib
import os
import stat as stat_module
import tomllib

from . import contracts as contracts_module
from . import patterns as patterns_module
from .textsafe import display_text

#: The only configuration schema this build interprets.
SCHEMA_VERSION = 1

#: Repository-relative name. Not configurable: a tool that lets you move its
#: configuration file has to explain which one is in force.
CONFIG_FILENAME = "aiqe.toml"

#: Domain separator for the configuration digest, so it cannot collide with a
#: digest of the same bytes taken for another purpose.
_DIGEST_DOMAIN = b"aiqe.config.v1\0"

#: An upper bound on a validator timeout, in seconds. A timeout is mandatory
#: precisely so that a wedged validator cannot hold a check open forever, and
#: a timeout of a year is a missing timeout with extra steps.
MAX_TIMEOUT_SECONDS = 86400

_TOP_LEVEL_FIELDS = frozenset({"schema", "surface", "validator"})
_SURFACE_FIELDS = frozenset({"paths", "quant", "contracts"})
_VALIDATOR_FIELDS = frozenset({"id", "run", "required", "timeout", "contracts"})

CONFIG_ABSENT = "CONFIG_ABSENT"
CONFIG_NOT_A_REGULAR_FILE = "CONFIG_NOT_A_REGULAR_FILE"
CONFIG_UNREADABLE = "CONFIG_UNREADABLE"
CONFIG_MALFORMED = "CONFIG_MALFORMED"
CONFIG_SCHEMA_MISSING = "CONFIG_SCHEMA_MISSING"
CONFIG_SCHEMA_UNSUPPORTED = "CONFIG_SCHEMA_UNSUPPORTED"
CONFIG_UNKNOWN_FIELD = "CONFIG_UNKNOWN_FIELD"
CONFIG_BLOCK_MALFORMED = "CONFIG_BLOCK_MALFORMED"
CONFIG_SURFACE_PATHS_INVALID = "CONFIG_SURFACE_PATHS_INVALID"
CONFIG_SURFACE_PATTERN_INVALID = "CONFIG_SURFACE_PATTERN_INVALID"
CONFIG_SURFACE_QUANT_INVALID = "CONFIG_SURFACE_QUANT_INVALID"
CONFIG_QUANT_WITHOUT_CONTRACTS = "CONFIG_QUANT_WITHOUT_CONTRACTS"
CONFIG_NON_QUANT_WITH_CONTRACTS = "CONFIG_NON_QUANT_WITH_CONTRACTS"
CONFIG_CONTRACT_INVALID = "CONFIG_CONTRACT_INVALID"
CONFIG_VALIDATOR_ID_INVALID = "CONFIG_VALIDATOR_ID_INVALID"
CONFIG_VALIDATOR_ID_DUPLICATE = "CONFIG_VALIDATOR_ID_DUPLICATE"
CONFIG_VALIDATOR_ARGV_INVALID = "CONFIG_VALIDATOR_ARGV_INVALID"
CONFIG_VALIDATOR_REQUIRED_INVALID = "CONFIG_VALIDATOR_REQUIRED_INVALID"
CONFIG_VALIDATOR_TIMEOUT_INVALID = "CONFIG_VALIDATOR_TIMEOUT_INVALID"


class ConfigError(Exception):
    """A configuration AIQE will not interpret. Always exit 3.

    `code` is the stable machine identity; the message names what was refused.
    """

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


class Surface(object):
    """One `[[surface]]` declaration."""

    __slots__ = ("index", "patterns", "quant", "contracts")

    def __init__(self, index, patterns, quant, contracts):
        self.index = index
        self.patterns = patterns
        self.quant = quant
        #: Sorted and de-duplicated, so two declarations that mean the same
        #: thing compare and render the same way.
        self.contracts = contracts

    def matches(self, path):
        for pattern in self.patterns:
            if pattern.matches(path):
                return True
        return False


class Validator(object):
    """One `[[validator]]` declaration, and its semantic definition digest."""

    __slots__ = ("index", "id", "argv", "required", "timeout", "contracts")

    def __init__(self, index, identifier, argv, required, timeout, contracts):
        self.index = index
        self.id = identifier
        self.argv = argv
        self.required = required
        self.timeout = timeout
        self.contracts = contracts

    @property
    def generic(self):
        """A validator bound to no contract is a generic task validator."""
        return not self.contracts


class Config(object):
    """A parsed, validated `aiqe.toml`."""

    __slots__ = ("schema", "surfaces", "validators", "digest", "raw_size")

    def __init__(self, schema, surfaces, validators, digest, raw_size):
        self.schema = schema
        self.surfaces = surfaces
        self.validators = validators
        #: Digest of the file's raw bytes.
        self.digest = digest
        self.raw_size = raw_size

    def validator(self, identifier):
        for validator in self.validators:
            if validator.id == identifier:
                return validator
        return None


def config_path(worktree):
    """Absolute path of the configuration file, as bytes."""
    return os.path.join(worktree, os.fsencode(CONFIG_FILENAME))


def present(worktree):
    """Is there a configuration file at the repository root?

    A read, and only a read: this creates nothing and follows nothing.
    """
    try:
        stat = os.lstat(config_path(worktree))
    except OSError:
        return False
    return stat_module.S_ISREG(stat.st_mode)


def read_raw(worktree):
    """The configuration file's raw bytes. Raises `ConfigError`.

    `lstat` before `open`, and a refusal for anything that is not a regular
    file. A symlinked `aiqe.toml` would make the configuration in force depend
    on something outside the repository, which is precisely the ambiguity a
    fail-closed reader exists to refuse.
    """
    path = config_path(worktree)
    try:
        stat = os.lstat(path)
    except FileNotFoundError:
        raise ConfigError(
            CONFIG_ABSENT,
            "no %s at the repository root. Run `aiqe init` to write one."
            % (CONFIG_FILENAME,),
        )
    except OSError as exc:
        raise ConfigError(
            CONFIG_UNREADABLE,
            "%s could not be inspected: %s" % (CONFIG_FILENAME, exc.strerror),
        )

    if not stat_module.S_ISREG(stat.st_mode):
        raise ConfigError(
            CONFIG_NOT_A_REGULAR_FILE,
            "%s exists but is not a regular file. AIQE does not follow a "
            "configuration file to somewhere else." % (CONFIG_FILENAME,),
        )

    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise ConfigError(
            CONFIG_UNREADABLE,
            "%s could not be read: %s" % (CONFIG_FILENAME, exc.strerror),
        )


def digest_bytes(raw):
    """The configuration digest, over the file's raw bytes."""
    return "sha256:" + hashlib.sha256(_DIGEST_DOMAIN + raw).hexdigest()


def load(worktree):
    """Read and validate `./aiqe.toml`. Raises `ConfigError`."""
    return parse(read_raw(worktree))


def parse(raw):
    """Validate raw configuration bytes into a `Config`. Raises `ConfigError`."""
    try:
        document = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ConfigError(
            CONFIG_MALFORMED,
            "%s is not valid UTF-8, which TOML requires (%s)."
            % (CONFIG_FILENAME, exc),
        )
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            CONFIG_MALFORMED, "%s is not valid TOML: %s" % (CONFIG_FILENAME, exc)
        )

    _refuse_unknown(document, _TOP_LEVEL_FIELDS, "the top level of " + CONFIG_FILENAME)

    if "schema" not in document:
        raise ConfigError(
            CONFIG_SCHEMA_MISSING,
            "%s does not declare `schema`. AIQE will not guess which schema a "
            "configuration was written for." % (CONFIG_FILENAME,),
        )
    schema = document["schema"]
    if schema is not SCHEMA_VERSION and schema != SCHEMA_VERSION:
        raise ConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "%s declares schema %r, and this build interprets schema %d."
            % (CONFIG_FILENAME, schema, SCHEMA_VERSION),
        )
    if isinstance(schema, bool):
        raise ConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "`schema` must be the integer %d." % (SCHEMA_VERSION,),
        )

    surfaces = _parse_surfaces(document.get("surface", []))
    validators = _parse_validators(document.get("validator", []))

    return Config(
        SCHEMA_VERSION, surfaces, validators, digest_bytes(raw), len(raw)
    )


# --- Surfaces --------------------------------------------------------------


def _parse_surfaces(blocks):
    if not isinstance(blocks, list):
        raise ConfigError(
            CONFIG_BLOCK_MALFORMED,
            "`surface` must be written as `[[surface]]` blocks.",
        )

    surfaces = []
    for index, block in enumerate(blocks):
        where = "[[surface]] #%d" % (index + 1,)
        if not isinstance(block, dict):
            raise ConfigError(CONFIG_BLOCK_MALFORMED, "%s is not a table." % (where,))
        _refuse_unknown(block, _SURFACE_FIELDS, where)

        patterns = _parse_patterns(block, where)
        quant = _parse_quant(block, where)
        declared = _parse_contracts(block, where)

        if quant and not declared:
            raise ConfigError(
                CONFIG_QUANT_WITHOUT_CONTRACTS,
                "%s declares quant = true but no contracts. A quant surface "
                "with no obligation is a surface nothing is required to check, "
                "which is the false green this product exists to refuse."
                % (where,),
            )
        if not quant and declared:
            raise ConfigError(
                CONFIG_NON_QUANT_WITH_CONTRACTS,
                "%s declares quant = false and also declares contracts. A "
                "non-quant surface carries no contract obligations, so the "
                "declaration says two different things." % (where,),
            )

        surfaces.append(Surface(index, tuple(patterns), quant, tuple(declared)))
    return tuple(surfaces)


def _parse_patterns(block, where):
    if "paths" not in block:
        raise ConfigError(
            CONFIG_SURFACE_PATHS_INVALID, "%s declares no `paths`." % (where,)
        )
    raw = block["paths"]
    if not isinstance(raw, list) or not raw:
        raise ConfigError(
            CONFIG_SURFACE_PATHS_INVALID,
            "%s must declare `paths` as a non-empty array of patterns."
            % (where,),
        )

    compiled = []
    for item in raw:
        if not isinstance(item, str):
            raise ConfigError(
                CONFIG_SURFACE_PATHS_INVALID,
                "%s declares a path pattern that is not a string: %r"
                % (where, item),
            )
        try:
            compiled.append(patterns_module.compile_pattern(item))
        except patterns_module.PatternError as error:
            raise ConfigError(
                CONFIG_SURFACE_PATTERN_INVALID, "%s: %s" % (where, error.message)
            )
    return compiled


def _parse_quant(block, where):
    if "quant" not in block:
        raise ConfigError(
            CONFIG_SURFACE_QUANT_INVALID,
            "%s does not declare `quant`. AIQE does not infer quant = false "
            "from an absence of evidence: a surface nobody classified is not "
            "the same as a surface someone classified as ordinary code."
            % (where,),
        )
    quant = block["quant"]
    if not isinstance(quant, bool):
        raise ConfigError(
            CONFIG_SURFACE_QUANT_INVALID,
            "%s declares `quant` as %r; it must be true or false."
            % (where, quant),
        )
    return quant


def _parse_contracts(block, where):
    raw = block.get("contracts")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(
            CONFIG_CONTRACT_INVALID,
            "%s must declare `contracts` as an array." % (where,),
        )
    seen = []
    for item in raw:
        if not contracts_module.is_valid_identifier(item):
            raise ConfigError(
                CONFIG_CONTRACT_INVALID,
                "%s declares %r as a contract. A contract identifier is "
                "upper-case ASCII letters, digits and underscores, beginning "
                "with a letter." % (where, item),
            )
        if item in seen:
            raise ConfigError(
                CONFIG_CONTRACT_INVALID,
                "%s declares contract %s more than once." % (where, item),
            )
        seen.append(item)
    return sorted(seen)


# --- Validators ------------------------------------------------------------


def _parse_validators(blocks):
    if not isinstance(blocks, list):
        raise ConfigError(
            CONFIG_BLOCK_MALFORMED,
            "`validator` must be written as `[[validator]]` blocks.",
        )

    validators = []
    identifiers = set()
    for index, block in enumerate(blocks):
        where = "[[validator]] #%d" % (index + 1,)
        if not isinstance(block, dict):
            raise ConfigError(CONFIG_BLOCK_MALFORMED, "%s is not a table." % (where,))
        _refuse_unknown(block, _VALIDATOR_FIELDS, where)

        identifier = _parse_validator_id(block, where)
        if identifier in identifiers:
            raise ConfigError(
                CONFIG_VALIDATOR_ID_DUPLICATE,
                "two validators are declared with id %r. A validator id "
                "names one definition, and `--allow` and recorded consent "
                "both address it by name." % (identifier,),
            )
        identifiers.add(identifier)
        where = "[[validator]] %s" % (display_text(identifier),)

        argv = _parse_argv(block, where)
        required = _parse_required(block, where)
        timeout = _parse_timeout(block, where)
        declared = _parse_contracts(block, where)

        validators.append(
            Validator(index, identifier, argv, required, timeout, tuple(declared))
        )
    return tuple(validators)


def _parse_validator_id(block, where):
    if "id" not in block:
        raise ConfigError(
            CONFIG_VALIDATOR_ID_INVALID, "%s declares no `id`." % (where,)
        )
    identifier = block["id"]
    if not isinstance(identifier, str) or not identifier:
        raise ConfigError(
            CONFIG_VALIDATOR_ID_INVALID,
            "%s declares `id` as %r; it must be a non-empty string."
            % (where, identifier),
        )
    for character in identifier:
        if character.isascii() and (character.isalnum() or character in "._-"):
            continue
        raise ConfigError(
            CONFIG_VALIDATOR_ID_INVALID,
            "%s declares id %r. A validator id is ASCII letters, digits, "
            "'.', '_' and '-': it is typed on the command line after "
            "`--allow`, and it appears in output." % (where, identifier),
        )
    return identifier


def _parse_argv(block, where):
    if "run" not in block:
        raise ConfigError(
            CONFIG_VALIDATOR_ARGV_INVALID, "%s declares no `run`." % (where,)
        )
    raw = block["run"]
    if not isinstance(raw, list) or not raw:
        raise ConfigError(
            CONFIG_VALIDATOR_ARGV_INVALID,
            "%s must declare `run` as a non-empty argument vector, for "
            "example run = [\"pytest\", \"-q\"]. There is no shell: a string "
            "would have to be split by somebody's quoting rules, and AIQE "
            "does not own that decision." % (where,),
        )
    argv = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise ConfigError(
                CONFIG_VALIDATOR_ARGV_INVALID,
                "%s declares an argument that is not a non-empty string: %r"
                % (where, item),
            )
        if "\0" in item:
            raise ConfigError(
                CONFIG_VALIDATOR_ARGV_INVALID,
                "%s declares an argument containing a NUL byte." % (where,),
            )
        argv.append(item)
    return tuple(argv)


def _parse_required(block, where):
    if "required" not in block:
        raise ConfigError(
            CONFIG_VALIDATOR_REQUIRED_INVALID,
            "%s does not declare `required`. Whether a validator is a "
            "completion obligation or a signal is the most consequential "
            "thing about it, and it is not defaulted." % (where,),
        )
    required = block["required"]
    if not isinstance(required, bool):
        raise ConfigError(
            CONFIG_VALIDATOR_REQUIRED_INVALID,
            "%s declares `required` as %r; it must be true or false."
            % (where, required),
        )
    return required


def _parse_timeout(block, where):
    if "timeout" not in block:
        raise ConfigError(
            CONFIG_VALIDATOR_TIMEOUT_INVALID,
            "%s declares no `timeout`. A validator runs as a child process "
            "with no supervision, so there is no default: an unbounded check "
            "is a check that can never report anything." % (where,),
        )
    timeout = block["timeout"]
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        raise ConfigError(
            CONFIG_VALIDATOR_TIMEOUT_INVALID,
            "%s declares `timeout` as %r; it must be a whole number of "
            "seconds." % (where, timeout),
        )
    if timeout < 1 or timeout > MAX_TIMEOUT_SECONDS:
        raise ConfigError(
            CONFIG_VALIDATOR_TIMEOUT_INVALID,
            "%s declares timeout = %d; it must be between 1 and %d seconds."
            % (where, timeout, MAX_TIMEOUT_SECONDS),
        )
    return timeout


def _refuse_unknown(table, allowed, where):
    """Refuse an unrecognised key rather than ignoring it.

    A permissive reader turns `requred = true` into an optional validator and
    a `qaunt = true` surface into an unclassified one. Both are green results
    that mean nothing, and neither produces a message anybody sees.

    The rejected key is named back to the user, and a TOML quoted key can
    contain any character at all - including the ones a terminal acts on. It
    goes through the same escaping as every other repository-controlled string
    AIQE prints.
    """
    unknown = sorted(key for key in table if key not in allowed)
    if unknown:
        raise ConfigError(
            CONFIG_UNKNOWN_FIELD,
            "%s declares unknown field%s %s. AIQE refuses configuration it "
            "does not understand rather than ignoring it."
            % (
                where,
                "" if len(unknown) == 1 else "s",
                ", ".join(display_text(key) for key in unknown),
            ),
        )

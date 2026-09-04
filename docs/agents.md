# Working with Claude Code and Codex

AIQE is an ordinary command-line program. That is the entire integration.

```
NO plugin        NO extension      NO MCP server
NO hook          NO wrapper        NO adapter
```

There is nothing to install into your agent, and nothing here describes software that
does not exist. Your agent runs `aiqe` the way it runs `pytest` or `git`, and the
receipt it produces is a thing the agent cannot write for itself.

## The shape of a session

```bash
aiqe doctor
aiqe task start --own src/strategy/alpha.py --own tests/test_alpha.py
# … the agent edits exactly those files …
aiqe check --allow unit --allow causality
aiqe commit -m "bounded completion"
aiqe receipt
```

Three things about that sequence are the whole point, and each of them is a rule about
who does what.

**You declare the scope, before the agent starts.** `aiqe task start` fixes an exact
pathset that cannot widen. Declaring it after the agent has finished is a description of
what happened, not a bound on it — and a scope chosen to match the files that were
already touched bounds nothing at all.

**You give consent, per validator, on this machine.** `aiqe.toml` is tracked content: a
validator declaration names a command AIQE would otherwise run as you. Consent is bound
to the exact definition by a digest, and changing any semantic field revokes it.

`--allow <id>` is where that can quietly stop being yours. A flag the agent writes for
itself is the agent consenting on your behalf, to a validator declared in content the
agent can also edit. Pin the ids you are willing to run, or approve them interactively
and let the agent meet `CONSENT_REQUIRED` when it reaches one you have not.
See [`check.md`](check.md#consent).

**The verdict is not negotiable by the agent.** `aiqe receipt` recomputes its binding
rather than trusting a stored result, and `REVIEWABLE` requires a bounded commit whose
parent, pathset and content were all proved. An agent that reports success is making a
claim; the receipt is the artifact.

## Non-interactive use

An agent runs commands without a terminal, and AIQE behaves accordingly rather than
hanging on a prompt:

```
--format json          machine-readable output from doctor, check and receipt
--allow <id>           authorise one validator for one run; records nothing
no terminal            never prompts. An unconsented validator is UNKNOWN with
                       CONSENT_REQUIRED, which is neither a pass nor a failure
exit 0 / 1 / 2 / 3     reviewable / fail / incomplete / unsupported
```

Exit status is uniform across commands and is the thing to branch on:
[`architecture.md`](architecture.md#exit-semantics).

## What to put in `CLAUDE.md` or `AGENTS.md`

Keep it short, and keep the two decisions that are yours out of the agent's hands:

```markdown
## Completion protocol

A change is complete when `aiqe receipt` says REVIEWABLE. Not when the tests
pass, and not when you say it is done.

- The owned scope is declared before you start. Do not run `aiqe task start`,
  and do not widen the scope by any other means.
- Run `aiqe check` after editing. If it reports COVERAGE_GAP, say so and stop:
  the missing check is work, not an obstacle to route around.
- Run `aiqe commit -m "<message>"` to complete. If it refuses, report the
  reason code verbatim. Do not use `git commit`, `git add`, `git stash` or
  `git checkout` to make the refusal go away.
- Paste the output of `aiqe receipt` into your final message.
```

The last line of that block is the one worth keeping if you keep only one.

## What `aiqe doctor` tells you about your agent

Doctor reports whether an agent's configuration **in this repository** grants
unconstrained execution, under rules narrow enough to state exactly:

```
CLAUDE_PERMISSIONS_BROAD    .claude/settings.json or settings.local.json sets
                            permissions.defaultMode to bypassPermissions, or
                            allows shell access with no constraint on the command
CODEX_PERMISSIONS_BROAD     .codex/config.toml sets approval_policy = "never" or
                            sandbox_mode = "danger-full-access"
AGENT_CONFIG_UNREADABLE     a settings file is present and could not be parsed
```

Anything else is reported as **present**, never as *bounded*. Doctor does not certify an
agent configuration as safe; it recognises one shape, and says so. Full rules:
[`doctor.md`](doctor.md).

## What this does not do

AIQE does not supervise your agent, does not read its output, does not intercept its
tool calls and does not sandbox it. It bounds a commit and reports what was checked.
An agent that can run shell commands can do anything you can do, and AIQE is not the
control that prevents it — [`../SECURITY.md`](../SECURITY.md) states that boundary
exactly.

Neither does AIQE know which agent wrote a change. Nothing in a task record, an
evidence record or a receipt names an agent, a model or a vendor, and no telemetry is
sent anywhere.

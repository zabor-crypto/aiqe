"""Fixture construction helpers shared by the benchmark families.

Building a fixture is allowed to write - that is what building a repository
means. Only the operation under measurement must not.

One rule here is not obvious. Git may start background maintenance after a
write, and that process outlives the command: it creates
`.git/objects/maintenance.lock` and removes it when it finishes. If it finishes
during a measurement window, the harness sees a repository file disappear and
attributes it to the product. That false reading was observed, so every
fixture-construction invocation disables it, and fixtures are quiescent before
they are measured.
"""

import os
import subprocess
import sys


#: A fixture that has not finished in this many seconds is a broken fixture.
BUILD_TIMEOUT_SECONDS = 60


#: Applied to every fixture-construction invocation.
#:
#: Git may start background maintenance after a write, and that process
#: outlives the command: it creates `.git/objects/maintenance.lock` and
#: removes it when it finishes. If it finishes during a measurement window,
#: the harness sees a repository file disappear and attributes it to Doctor.
#: That is a false reading, and it was observed. Fixtures are built quiescent
#: instead, so a repository that changes during measurement means something
#: real changed it.
_NO_BACKGROUND_MAINTENANCE = ("-c", "gc.auto=0", "-c", "maintenance.auto=false")


def git(cwd, *args, **kwargs):
    """Run Git while building a fixture.

    Fixture construction is allowed to write - that is what building a
    repository means. Only the Doctor run under measurement must not.
    """
    check = kwargs.pop("check", True)
    env = kwargs.pop("env", None)
    proc = subprocess.run(
        ("git",) + _NO_BACKGROUND_MAINTENANCE + args,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=BUILD_TIMEOUT_SECONDS,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "fixture git %s failed: %s" % (" ".join(args), proc.stderr.decode("utf-8", "replace"))
        )
    return proc


def write(path, text, mode=None):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as handle:
        handle.write(text)
    if mode is not None:
        os.chmod(path, mode)


def canary(path, marker, body="exit 0"):
    """Install an executable script that records the fact that it ran.

    The default body exits immediately. A filter driver needs to pass content
    through instead, so it overrides the body.
    """
    write(
        path,
        "#!/bin/sh\n: > %s\n%s\n" % (_quote(marker), body),
        mode=0o755,
    )


def _quote(path):
    return "'" + path.replace("'", "'\\''") + "'"


def init_repo(root, env):
    os.makedirs(root)
    git(root, "init", "--quiet", "--initial-branch=main", env=env)
    git(root, "config", "user.name", "AIQE Fixture", env=env)
    git(root, "config", "user.email", "fixture@example.invalid", env=env)
    git(root, "config", "commit.gpgsign", "false", env=env)
    return root


def commit_all(root, message, env):
    git(root, "add", "--all", env=env)
    git(root, "commit", "--quiet", "--message", message, env=env)



def platform_supports(platform):
    """Is a platform-restricted case applicable to the machine running it?"""
    if platform is None:
        return True
    if platform == "linux":
        return sys.platform.startswith("linux")
    raise ValueError("unknown fixture platform restriction %r" % (platform,))



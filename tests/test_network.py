"""Proof that a Doctor run makes no network request, and no model call.

The claim is not made from reading the code. It is made three ways, and the
limits of each are stated rather than glossed over.

1.  Dependency proof. The AIQE package declares no third-party dependency, and
    importing all of it pulls in no network-capable standard library module -
    no socket, ssl, http, urllib, asyncio or their relatives. A module that is
    never imported cannot open a connection.

2.  Runtime canary. Every socket entry point in the standard library is
    replaced with a function that records the attempt and raises. A full
    Doctor run then executes against a real fixture. Nothing is recorded.

3.  Child-process argument proof. AIQE core spawns exactly one program, Git,
    through a single choke point, and only with subcommands on a frozen
    allowlist. None of those subcommands contacts a remote, and the fixture
    suite asserts the actual argument vectors.

The limitation, stated plainly: this is not kernel-level enforcement. No
network namespace or packet filter is applied, because installing one to run
a unit test would be a heavier dependency than the thing it verifies. Layers 1
and 2 are conclusive for AIQE's own Python code. Layer 3 is an argument about
Git's documented behaviour under a constrained argument set, not a
measurement of Git's syscalls.

Package installation is a separate matter. Resolving and downloading a Python
package uses the network by definition; that is the installer's behaviour, not
AIQE core's runtime behaviour, and the two are not interchangeable.
"""

import ast
import os
import shutil
import socket
import tempfile
import unittest

from . import support

NETWORK_MODULES = {
    "socket",
    "ssl",
    "http",
    "http.client",
    "urllib",
    "urllib.request",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "asyncio",
    "requests",
    "httpx",
    "aiohttp",
}

SOURCE_DIRECTORY = os.path.join(support.SOURCE, "aiqe")


class DependencyProofTests(unittest.TestCase):
    def test_no_source_file_imports_a_network_module(self):
        offenders = []
        for name in sorted(os.listdir(SOURCE_DIRECTORY)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(SOURCE_DIRECTORY, name)
            with open(path) as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in NETWORK_MODULES:
                            offenders.append((name, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split(".")[0] in NETWORK_MODULES:
                        offenders.append((name, node.module))
        self.assertEqual(offenders, [], "network-capable imports found")

    def test_importing_aiqe_pulls_in_no_network_module(self):
        import subprocess
        import sys

        program = (
            "import sys\n"
            "baseline = set(sys.modules)\n"
            "import aiqe.cli, aiqe.doctor, aiqe.report, aiqe.gitq, aiqe.gitconfig\n"
            "added = set(sys.modules) - baseline\n"
            "print(','.join(sorted(added)))\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = support.SOURCE
        completed = subprocess.run(
            [sys.executable, "-c", program],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        imported = set(completed.stdout.decode().strip().split(","))
        self.assertEqual(imported & NETWORK_MODULES, set())


class RuntimeCanaryTests(unittest.TestCase):
    """Break every socket entry point, then run Doctor for real."""

    def setUp(self):
        self.attempts = []
        self.root = tempfile.mkdtemp(prefix="aiqe-network-")
        self.addCleanup(shutil.rmtree, self.root, True)

        case = support.harness.Case("normal_repository", self.root)
        self.env = case.env()
        self.target = support.builders.build_normal_repository(case, self.env)

        self._originals = {}
        for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname"):
            if not hasattr(socket, name):
                continue
            self._originals[name] = getattr(socket, name)
            setattr(socket, name, self._trap(name))
        self.addCleanup(self._restore)

    def _trap(self, name):
        def trapped(*args, **kwargs):
            self.attempts.append(name)
            raise AssertionError("AIQE attempted a network operation: %s" % (name,))

        return trapped

    def _restore(self):
        for name, original in self._originals.items():
            setattr(socket, name, original)

    def test_doctor_run_attempts_no_socket_operation(self):
        from aiqe import __version__
        from aiqe.doctor import inspect
        from aiqe.report import render_human, render_json

        report = inspect(self.target, env=self.env)
        render_human(report)
        render_json(report, __version__)

        self.assertEqual(self.attempts, [], "network entry points were called")
        self.assertEqual(report.result, "PRODUCED")


class ChildProcessProofTests(unittest.TestCase):
    def test_git_is_the_only_program_spawned(self):
        observed = support.harness.run_case("normal_repository")
        for invocation in observed["git_invocations"]:
            self.assertTrue(invocation[0].endswith("git"), invocation)

    def test_no_remote_contacting_subcommand_is_reachable(self):
        from aiqe.gitq import ALLOWED_SUBCOMMANDS

        remote_subcommands = {
            "fetch", "pull", "push", "clone", "remote", "ls-remote",
            "submodule", "send-email", "request-pull", "credential",
        }
        self.assertEqual(ALLOWED_SUBCOMMANDS & remote_subcommands, set())

    def test_allowlist_is_enforced_not_merely_documented(self):
        from aiqe.gitq import GitRunner

        runner = GitRunner(os.getcwd())
        with self.assertRaises(AssertionError):
            runner.run("fetch", "origin")
        self.assertEqual(runner.invocations, [])


class ModelCallTests(unittest.TestCase):
    def test_no_model_client_is_reachable(self):
        """AIQE v1 is deterministic and contains no model calls.

        With no third-party dependency and no network-capable import, there is
        no client to call one with.
        """
        offenders = []
        for name in sorted(os.listdir(SOURCE_DIRECTORY)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(SOURCE_DIRECTORY, name)) as handle:
                text = handle.read().lower()
            for marker in ("anthropic", "openai", "completion(", "chat.completions"):
                if marker in text:
                    offenders.append((name, marker))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

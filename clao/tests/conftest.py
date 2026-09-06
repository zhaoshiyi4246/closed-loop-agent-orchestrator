"""Offline suite: never launch a real AO or semantic-model executable."""
import os
import subprocess

import pytest


@pytest.fixture(autouse=True)
def no_live_role_processes(monkeypatch):
    original = subprocess.Popen
    def offline_popen(args, *positional, **kwargs):
        first = args[0] if isinstance(args, (list, tuple)) else args.split()[0]
        name = os.path.basename(str(first)).lower()
        if name in {"ao", "ao.exe", "ao.cmd", "codex", "codex.exe", "codex.cmd", "claude", "claude.exe"}:
            raise RuntimeError("offline test blocked real AO/model process")
        return original(args, *positional, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", offline_popen)

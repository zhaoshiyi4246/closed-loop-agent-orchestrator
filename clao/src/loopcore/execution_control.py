"""Cancellation of CLAO-owned local processes, scoped to one Controller tick."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
import signal
import subprocess
import time

CURRENT = ContextVar('clao_execution_control', default=None)


class ExecutionCancelled(BaseException):
    """Unwind without semantic retries or applying an interrupted result."""


class ExecutionControl:
    def __init__(self, event, store=None, mission_id=None):
        self.event = event
        self.store, self.mission_id = store, mission_id
        self.unconfirmed = set()

    def check(self):
        if self.unconfirmed and not self.event.is_set():
            raise RuntimeError('local subprocess termination UNKNOWN; no further controlled execution')
        if self.store and self.store.mission_stop_requested(self.mission_id):
            self.event.set()
        if self.event.is_set():
            raise ExecutionCancelled('cancellation requested')

    @contextmanager
    def bind(self):
        token = CURRENT.set(self)
        try:
            yield
        finally:
            CURRENT.reset(token)

    def stop_process(self, proc):
        # Only a process created below is addressed, including its descendants.
        # Failure remains an explicit unknown; never claim cancellation done.
        if os.name == 'nt':
            result = subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                                    capture_output=True, timeout=10)
            confirmed = result.returncode == 0
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                confirmed = True
            except ProcessLookupError:
                confirmed = True
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            confirmed = False
        if not confirmed:
            self.unconfirmed.add(proc.pid)
        return confirmed

    def run(self, args, *, input=None, timeout=None, capture_output=False, **kwargs):
        self.check()
        if capture_output:
            kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if input is not None:
            kwargs['stdin'] = subprocess.PIPE
        kwargs.update(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        if os.name != 'nt':
            kwargs['start_new_session'] = True
        proc = subprocess.Popen(args, **kwargs)
        try:
            if self.store:
                self.store.record_mission(self.mission_id, {'local_execution': dict(status='running', pid=proc.pid, started_epoch=time.time())})
        except BaseException:
            self.stop_process(proc)
            raise
        end = time.monotonic() + timeout if timeout is not None else None
        first = True
        try:
            while True:
                if self.store and self.store.mission_stop_requested(self.mission_id):
                    self.event.set()
                if self.event.is_set():
                    self.stop_process(proc)
                    raise ExecutionCancelled('local execution stopped or awaiting confirmation')
                if end is not None and time.monotonic() >= end:
                    self.stop_process(proc)
                    raise subprocess.TimeoutExpired(args, timeout)
                try:
                    out, err = proc.communicate(input=input if first else None, timeout=0.1)
                    self.check()
                    return subprocess.CompletedProcess(args, proc.returncode, out, err)
                except subprocess.TimeoutExpired:
                    first = False
        finally:
            if proc.poll() is None:
                self.stop_process(proc)
            if self.store:
                self.store.record_mission(self.mission_id, {'local_execution': dict(
                    status='unknown' if proc.pid in self.unconfirmed else 'stopped', pid=proc.pid,
                    ended_epoch=time.time(), returncode=proc.returncode)})
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream:
                    stream.close()


def run(*args, **kwargs):
    control = CURRENT.get()
    return control.run(*args, **kwargs) if control is not None else subprocess.run(*args, **kwargs)


def checkpoint():
    control = CURRENT.get()
    if control is not None:
        control.check()

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable
from pathlib import Path


class RenardoRuntime:
    def __init__(self, root: Path, event_sink: Callable[[str, str, str, dict], None]) -> None:
        self.root = root
        self._event_sink = event_sink
        self._proc: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._watch_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def ensure_running(self) -> None:
        async with self._lock:
            if self.is_running():
                return

            env = os.environ.copy()
            env["PATH"] = f"/Applications/SuperCollider.app/Contents/MacOS:{env.get('PATH', '')}"

            self._proc = await asyncio.create_subprocess_exec(
                "bash",
                "tools/renardo_boot.sh",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.root),
                env=env,
            )
            self._stdout_task = asyncio.create_task(self._read_stream("stdout"))
            self._stderr_task = asyncio.create_task(self._read_stream("stderr"))
            self._watch_task = asyncio.create_task(self._watch_process())
            self._event_sink("runtime", "info", "Renardo process started", {})

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def _read_stream(self, stream_name: str) -> None:
        if self._proc is None:
            return
        stream = self._proc.stdout if stream_name == "stdout" else self._proc.stderr
        if stream is None:
            return

        while True:
            line = await stream.readline()
            if not line:
                break
            message = line.decode(errors="replace").rstrip()
            self._event_sink("renardo", "info", message, {"stream": stream_name})

    async def _watch_process(self) -> None:
        if self._proc is None:
            return
        code = await self._proc.wait()
        self._event_sink("runtime", "error", "Renardo process exited", {"returncode": code})

    async def send_lines(self, source: str) -> None:
        if not self.is_running() or self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Renardo is not running")

        # Send line-by-line to mimic interactive terminal entry more closely.
        for raw_line in source.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            self._proc.stdin.write(line.encode("utf-8") + b"\n")
            await self._proc.stdin.drain()
            await asyncio.sleep(0.03)

        # Extra newline helps ensure final statement is consumed in REPL-like loops.
        self._proc.stdin.write(b"\n")
        await self._proc.stdin.drain()
        self._event_sink("runtime", "debug", "Sent commands", {"source": source})

    async def clear_clock(self) -> None:
        await self.send_lines("Clock.clear()")
        self._event_sink("runtime", "info", "Clock cleared", {})

    async def load_song(self, path: str) -> None:
        song = Path(path)
        if not song.is_absolute():
            song = self.root / song
        if not song.exists() or not song.is_file():
            raise FileNotFoundError(f"song not found: {song}")
        await self.send_lines(f"exec(open({str(song)!r}).read())")
        self._event_sink("runtime", "info", f"Loaded song: {song}", {})

    async def shutdown(self) -> None:
        if self._proc is None:
            return
        if self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()
            await self._proc.wait()

        for task in (self._stdout_task, self._stderr_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self._watch_task:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watch_task

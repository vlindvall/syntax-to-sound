#!/usr/bin/env python3
"""Apply local compatibility fixes for Renardo + SuperCollider on this machine."""

from __future__ import annotations

import inspect
from pathlib import Path


def patch_file(path: Path, replacements: list[tuple[str, str]]) -> bool:
    text = path.read_text()
    original = text
    for old, new in replacements:
        text = text.replace(old, new)
    if text != original:
        path.write_text(text)
        return True
    return False


def main() -> int:
    import renardo.supercollider_mgt.sclang_instances_mgt as sc_mgt

    changed = False

    sclang_path = Path(inspect.getsourcefile(sc_mgt) or "")
    if not sclang_path.exists():
        raise RuntimeError("Could not locate sclang_instances_mgt.py")

    changed |= patch_file(
        sclang_path,
        [
            ('self.sclang_exec = ["sclang", \'-i\', \'emacs\']',
             'self.sclang_exec = ["sclang", \'-i\', \'scqt\']'),
            ('raw = code_string.encode("utf-8") + b"\\x1b"',
             'raw = code_string.encode("utf-8") + b"\\x1b\\n"'),
        ],
    )

    # Normalize start_sclang_subprocess to always create/track this instance's process.
    source = sclang_path.read_text()
    old_block = """    def start_sclang_subprocess(self):
        if not self.is_sclang_running():
            #print("Auto Launching Renardo SC module with SynthDefManagement...")
            self.sclang_process = subprocess.Popen(
                args=self.sclang_exec,
                #shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
            )
            return True
        else:
            return False
"""
    new_block = """    def start_sclang_subprocess(self):
        # Always track the subprocess created by this Renardo instance.
        self.sclang_process = subprocess.Popen(
            args=self.sclang_exec,
            #shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
        )
        return True
"""
    if old_block in source:
        sclang_path.write_text(source.replace(old_block, new_block))
        changed = True

    sc_root = Path.home() / "Library" / "Application Support" / "SuperCollider"
    renardo_sc = sc_root / "Extensions" / "Renardo.sc"
    if renardo_sc.exists():
        changed |= patch_file(
            renardo_sc,
            [
                (
                    "server.options.numInputBusChannels = 16;",
                    "server.options.numInputBusChannels = 0;",
                )
            ],
        )

    # Avoid MIDI init crash on some macOS setups without configured MIDI destinations.
    start_file = sc_root / "start_renardo.scd"
    if start_file.exists():
        start_text = start_file.read_text()
        if "Renardo.midi;" in start_text:
            start_file.write_text(start_text.replace("Renardo.midi;", ""))
            changed = True

    print("prepare_renardo:", "updated" if changed else "already up-to-date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

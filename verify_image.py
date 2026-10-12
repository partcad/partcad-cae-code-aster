#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether this image can actually run the Code_Aster analyses.

Run at build time, so that an image which cannot is never published. The base
image's own `verify.py` checks the contract PartCAD talks to a container
through; this checks what this image adds: that `run_aster` is found where the
analyses look for it, and that it runs a study to the end. The mesher comes from
pip at run time and is not this image's to check.
"""

import os
import shutil
import subprocess
import sys
import tempfile

STUDY = """
DEBUT(LANG="EN")
values = DEFI_LIST_REEL(VALE=(1.0, 2.0, 3.0))
FIN()
"""


def main() -> int:
    failures = []
    run_aster = shutil.which("run_aster")
    if not run_aster:
        failures.append("run_aster is not on PATH")
    else:
        with tempfile.TemporaryDirectory() as work:
            with open(os.path.join(work, "study.comm"), "w") as f:
                f.write(STUDY)
            with open(os.path.join(work, "study.export"), "w") as f:
                f.write(
                    "P time_limit 300\nP memory_limit 1024\nP ncpus 1\nP mpi_nbcpu 1\n"
                    "F comm %s D 1\nF mess %s R 6\n" % (os.path.join(work, "study.comm"), os.path.join(work, "message"))
                )
            completed = subprocess.run(
                [run_aster, os.path.join(work, "study.export")], capture_output=True, text=True, cwd=work
            )
            if completed.returncode != 0:
                failures.append("run_aster could not run a study: %s" % (completed.stdout + completed.stderr)[-800:])
            else:
                print("run_aster at %s ran a study to the end" % run_aster)

    if failures:
        print("\nThis image cannot run the Code_Aster analyses:")
        for failure in failures:
            print("  * %s" % failure)
        return 1
    print("\nCode_Aster runs from this image.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

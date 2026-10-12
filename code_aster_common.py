#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Finding Code_Aster, running a study, and reading what it answered.

Everything the three analysis scripts share that is about Code_Aster rather
than about the physics.

**A study** is a command file (`.comm`, which is Python run by Code_Aster's own
interpreter), the mesh as a MED file, and an export file naming both. Each
script writes the command file; this module writes the rest, runs `run_aster`
and reads the answer back. The answer is not parsed out of Code_Aster's
message file: the command file ends by writing what was computed -- every node's
position and the field asked for, the frequencies -- as JSON, which is the one
format both sides read without help.

**Where it is.** `run_aster` named by `PARTCAD_CODE_ASTER`, then on `PATH`, then
in the sandbox's own conda environment, then where the usual installations put
it.

**The mesh** comes from gmsh as MED, with each boundary condition's faces a
named group. Not every gmsh can write MED: pip's wheels can, conda-forge's can,
Debian's cannot -- which is why this package's image gets gmsh from pip.
"""

import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys

# The meta-wrapper's directory is on 'sys.path' when PartCAD runs a script, and
# 'cae_support' lives there: what every implementation does around its solver.
import cae_support as support  # noqa: E402

RUN_ASTER_ENV = "PARTCAD_CODE_ASTER"
DIRECTORIES = ("/opt/code_aster/bin", "/opt/aster/bin", "/usr/local/bin", os.path.expanduser("~/code_aster/bin"))

ERROR = "error"
WARNING = "warning"
INFO = "info"
M2_PER_MM2 = 1e-6
MM_PER_M = 1000.0


def find_run_aster():
    """The 'run_aster' to run studies with."""
    named = os.environ.get(RUN_ASTER_ENV)
    if named:
        if os.path.isfile(named):
            return named
        raise support.ToolMissing("%s points at something that is not a file: %s" % (RUN_ASTER_ENV, named))
    found = shutil.which("run_aster")
    if found:
        return found
    places = [os.path.join(os.environ.get("CONDA_PREFIX") or sys.prefix, "bin")] + list(DIRECTORIES)
    for directory in places:
        candidate = os.path.join(directory, "run_aster")
        if os.path.isfile(candidate):
            return candidate
    raise support.ToolMissing(
        "Code_Aster is not available on this %s-%s machine. Two ways to have it: run with a container runtime "
        "available, which gets the image named by 'dockerImage:' in partcad.yaml and carries Code_Aster -- or "
        "install it here: 'conda install -c conda-forge code-aster' on x86_64 Linux and Windows, or EDF's "
        "salome_meca; then put run_aster on PATH, or point %s at it. Searched: PATH, %s"
        % (platform.system(), platform.machine(), RUN_ASTER_ENV, ", ".join(places))
    )


def mesh_part(request, groups, work, order):
    """Mesh the part as MED, each group named; return the gmsh mesh."""
    med = os.path.join(work, "part.med")
    mesh = support.mesh(request, groups, size=float(request.get("mesh_size", 0.05)), order=order, files=[med])
    if not os.path.isfile(med):
        raise support.ToolMissing(
            "This gmsh cannot write MED, which is the mesh format Code_Aster reads. pip's and conda-forge's gmsh "
            "can; a distribution's often cannot"
        )
    return mesh


# The head of every command file: the study starts, and a helper reads a field
# at every node. The script's own part follows it, reads the mesh into 'mesh',
# computes, and leaves what it found in 'ANSWER'.
PROLOGUE = """
DEBUT(LANG="EN")
import json as _json
import numpy as _numpy


def nodal(field, components):
    \"\"\"A field's components at every node, in the mesh's node order.\"\"\"
    simple = field.toSimpleFieldOnNodes()
    values, mask = simple.getValues()
    names = list(simple.getComponents())
    columns = [names.index(c) for c in components]
    return [[float(values[n, c]) if mask[n, c] else 0.0 for c in columns] for n in range(values.shape[0])]


mesh = LIRE_MAILLAGE(FORMAT="MED", UNITE=20)
"""

# The tail: the answer, as JSON, where the script reads it -- every node's
# position beside whatever the study put in 'ANSWER'.
EPILOGUE = """
_answer = {"coordinates": _numpy.asarray(mesh.getCoordinates().getValues()).reshape(-1, 3).tolist()}
_answer.update(ANSWER)
with open(%r, "w") as _out:
    _json.dump(_answer, _out)
FIN()
"""


def run(work, comm, mesh_file="part.med"):
    """Run a study on the mesh in 'work'; return the JSON it wrote.

    'comm' is the middle of the command file: 'PROLOGUE' has started the study
    and read the mesh into 'mesh' before it, and it ends by setting 'ANSWER'.
    """
    run_aster = find_run_aster()
    answer = os.path.join(work, "answer.json")
    with open(os.path.join(work, "study.comm"), "w") as f:
        f.write(PROLOGUE + comm + EPILOGUE % answer)
    with open(os.path.join(work, "study.export"), "w") as f:
        f.write(
            "P time_limit %d\nP memory_limit %d\nP ncpus 1\nP mpi_nbcpu 1\n"
            "F comm %s D 1\nF mmed %s D 20\nF mess %s R 6\n"
            % (
                3600,
                4096,
                os.path.join(work, "study.comm"),
                os.path.join(work, mesh_file),
                os.path.join(work, "message"),
            )
        )
    completed = subprocess.run(
        [run_aster, os.path.join(work, "study.export")],
        cwd=work,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    message = os.path.join(work, "message")
    text = open(message, errors="replace").read() if os.path.isfile(message) else completed.stdout + completed.stderr
    if completed.returncode != 0 or not os.path.isfile(answer):
        # Code_Aster's errors are framed blocks with '<F>' or '<EXCEPTION>' in
        # them, and the first is what stopped the study -- the ones after it
        # are the same failure reported again on the way out. A Python error
        # in the command file names itself on a line ending the traceback.
        lines = text.splitlines()
        marks = [k for k, line in enumerate(lines) if "<F>" in line or "<EXCEPTION>" in line]
        excerpt = lines[marks[0] : marks[0] + 20] if marks else lines[-20:]
        excerpt += [line for line in lines if re.match(r"^\w*(Error|Exception):", line)][:3]
        raise support.ToolFailed("Code_Aster could not finish the study:\n%s" % "\n".join(excerpt))
    with open(answer) as f:
        return json.load(f)


def by_position(answer, name, mesh):
    """A field Code_Aster computed, at the gmsh mesh's nodes, joined by position.

    Code_Aster numbers the nodes of the MED file its own way, so what the two
    copies of the mesh share is where each node is.
    """
    at = support.match_points(mesh.coordinates, answer["coordinates"], mesh.extent * 1e-6)
    values = answer[name]
    return [values[k] if k is not None else None for k in at]


def draw(path, mesh, values, low=None):
    """The part's surface coloured by one value per gmsh node, as glTF."""
    index = {int(tag): k for k, tag in enumerate(mesh.node_tags)}
    cells = []
    for _type, _tags, nodes in mesh.volumes:
        cells.extend([index[int(tag)] for tag in element[:4]] for element in nodes)
    numbers = [0.0 if value is None else float(value) for value in values]
    support.write_glb(path, mesh.coordinates, support.outer_triangles(cells, 4), numbers, low=low)


def norm(vector):
    return math.sqrt(sum(component * component for component in vector))


def nothing_covered(record):
    """The finding for a condition whose port covers no surface of the part."""
    return {
        "severity": WARNING,
        "message": (
            "The port covers no surface of the part, so the condition on it did nothing. Place the port on "
            "the face it means, or draw its interface with a sketch that lies on one."
        ),
        "where": record.get("port") or record.get("interface_label") or "a port",
    }


def group_list(names):
    """A Code_Aster tuple of group names."""
    return "(%s)" % ", ".join(repr(name) for name in names)

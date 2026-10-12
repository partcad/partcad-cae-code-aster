#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae dynamic`, by Code_Aster: the natural frequencies of one part, held as it is.

`fix:` holds the faces its ports cover still; the stiffness and mass matrices
are assembled and `CALC_MODES` finds the lowest `modes` frequencies and their
shapes. The model is the part coloured by how far each point moves in the first
mode; a first frequency under `min_frequency` is a finding.
"""

import os
import sys
import tempfile

# `runpy.run_path()` leaves the script's directory off `sys.path`, so the
# sibling module below is not importable without saying where it is.
sys.path.append(os.path.dirname(__file__))
import code_aster_common as aster  # noqa: E402
from code_aster_common import WARNING, support  # noqa: E402


def process(path, request):
    try:
        return _analyse(path, request)
    except (support.ToolMissing, support.ToolFailed) as e:
        return support.failed(e)


def _analyse(path, request):
    findings = []
    fixed, fixed_records, fixed_empty = support.condition_groups(request, "fix", "FIX")
    findings.extend(aster.nothing_covered(record) for record in fixed_empty)
    if not fixed_records:
        raise support.ToolFailed(
            "'dynamic:' holds nothing, so the part is free and its lowest modes are rigid-body motion at 0 Hz: "
            "name what holds it under 'fix:', on a port that covers a surface of the part"
        )
    modes = max(1, int(request.get("modes", 6)))

    with tempfile.TemporaryDirectory() as work:
        # A directory to keep the study in, for whoever is debugging one by hand.
        work = os.environ.get("PARTCAD_CODE_ASTER_STUDY") or work
        mesh = aster.mesh_part(request, fixed, work, int(request.get("mesh_order", 2)))
        answer = aster.run(work, _comm(request, fixed, modes))

    frequencies = [float(value) for value in answer["frequencies"]][:modes]
    if not frequencies:
        raise support.ToolFailed("Code_Aster found no modes")
    moved = [aster.norm(value) for value in answer["first_mode"]]
    peak = max(moved) or 1.0
    aster.draw(path, mesh, aster.by_position({**answer, "m": [value / peak for value in moved]}, "m", mesh), low=0.0)

    limit = request.get("min_frequency")
    if limit is not None and frequencies[0] < float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": "The part's first natural frequency is %.4g Hz, under the %.4g Hz it has to stay above: "
                "it will resonate with anything driving it near that." % (frequencies[0], float(limit)),
                "where": "first natural frequency",
            }
        )
    return {
        "success": True,
        "findings": findings,
        "warnings": [
            "Natural frequencies %s Hz, over %d elements"
            % (", ".join("%.5g" % value for value in frequencies), mesh.element_count)
        ],
    }


def _comm(request, fixed, modes):
    return """
model = AFFE_MODELE(MAILLAGE=mesh, AFFE=_F(TOUT="OUI", PHENOMENE="MECANIQUE", MODELISATION="3D"))
material = DEFI_MATERIAU(ELAS=_F(E=%.10g, NU=%.10g, RHO=%.10g))
assigned = AFFE_MATERIAU(MAILLAGE=mesh, AFFE=_F(TOUT="OUI", MATER=material))
held = AFFE_CHAR_MECA(MODELE=model, DDL_IMPO=_F(GROUP_MA=%s, DX=0.0, DY=0.0, DZ=0.0))
stiffness_elements = CALC_MATR_ELEM(OPTION="RIGI_MECA", MODELE=model, CHAM_MATER=assigned, CHARGE=held)
mass_elements = CALC_MATR_ELEM(OPTION="MASS_MECA", MODELE=model, CHAM_MATER=assigned, CHARGE=held)
numbering = NUME_DDL(MATR_RIGI=stiffness_elements)
stiffness = ASSE_MATRICE(MATR_ELEM=stiffness_elements, NUME_DDL=numbering)
mass = ASSE_MATRICE(MATR_ELEM=mass_elements, NUME_DDL=numbering)
modes = CALC_MODES(MATR_RIGI=stiffness, MATR_MASS=mass, OPTION="PLUS_PETITE", CALC_FREQ=_F(NMAX_FREQ=%d))
ANSWER = {
    "frequencies": [float(f) for f in modes.getAccessParameters()["FREQ"]],
    "first_mode": nodal(modes.getField("DEPL", 1), ["DX", "DY", "DZ"]),
}
""" % (
        float(request.get("youngs_modulus", 2.1e11)),
        float(request.get("poissons_ratio", 0.30)),
        float(request.get("density", 7850)),
        aster.group_list(fixed),
        modes,
    )


# Importable as a module by its tests, and executed by PartCAD's meta-wrapper
# under the run name below -- so nothing here runs on import.
if __name__ == "__partcad_export__":
    pass

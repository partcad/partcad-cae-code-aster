#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae fea`, by Code_Aster: a linear static stress analysis of one part.

`fix:` holds the faces its ports cover still in every direction (`DDL_IMPO`);
`load:` spreads its force evenly over the faces its ports cover, along -Z
(`FORCE_FACE`), which is where a weight goes; gravity acts on the part's own
mass too, unless `self_weight` is off (`PESANTEUR`). `MECA_STATIQUE` solves it on
quadratic tetrahedra, and the answer is the von Mises stress at every node and
how far each moved.
"""

import os
import sys
import tempfile

# `runpy.run_path()` leaves the script's directory off `sys.path`, so the
# sibling module below is not importable without saying where it is.
sys.path.append(os.path.dirname(__file__))
import code_aster_common as aster  # noqa: E402
from code_aster_common import ERROR, WARNING, support  # noqa: E402


def process(path, request):
    try:
        return _analyse(path, request)
    except (support.ToolMissing, support.ToolFailed) as e:
        return support.failed(e)


def _analyse(path, request):
    findings = []
    fixed, fixed_records, fixed_empty = support.condition_groups(request, "fix", "FIX")
    loaded, loaded_records, loaded_empty = support.condition_groups(request, "load", "LOAD")
    findings.extend(aster.nothing_covered(record) for record in fixed_empty + loaded_empty)
    if not fixed_records:
        raise support.ToolFailed(
            "'fea:' holds nothing, so the part is free to float: name at least one interface under 'fix:', "
            "on a port that covers a surface of the part"
        )

    with tempfile.TemporaryDirectory() as work:
        # A directory to keep the study in, for whoever is debugging one by hand.
        work = os.environ.get("PARTCAD_CODE_ASTER_STUDY") or work
        mesh = aster.mesh_part(request, {**fixed, **loaded}, work, int(request.get("mesh_order", 2)))
        answer = aster.run(work, _comm(request, fixed, loaded, loaded_records))

    displacement = [aster.norm(value) for value in answer["displacement"]]
    stress = [value[0] for value in answer["von_mises"]]
    aster.draw(path, mesh, aster.by_position({**answer, "s": stress}, "s", mesh), low=0.0)

    peak_stress = max(stress)
    peak_displacement = max(displacement) * aster.MM_PER_M
    findings.extend(_verdict(peak_stress, peak_displacement, request))
    return {
        "success": True,
        "findings": findings,
        "warnings": [
            "Peak von Mises stress %.4g MPa, peak displacement %.4g mm, over %d elements"
            % (peak_stress / 1e6, peak_displacement, mesh.element_count)
        ],
    }


def _comm(request, fixed, loaded, loaded_records):
    density = float(request.get("density", 7850))
    gravity = 9.81 if request.get("self_weight", True) else 0.0
    faces = []
    for name, record in zip(loaded, loaded_records):
        traction = float(record["load"]) / (float(record["area"]) * aster.M2_PER_MM2)
        faces.append("_F(GROUP_MA=%r, FZ=%.10g)" % (name, -traction))
    loads = "pulled = AFFE_CHAR_MECA(MODELE=model, FORCE_FACE=(%s,))\n" % ", ".join(faces) if faces else ""
    weight = (
        "weight = AFFE_CHAR_MECA(MODELE=model, PESANTEUR=_F(GRAVITE=%.10g, DIRECTION=(0.0, 0.0, -1.0)))\n" % gravity
        if gravity
        else ""
    )
    excitations = (
        ["_F(CHARGE=held)"] + (["_F(CHARGE=pulled)"] if faces else []) + (["_F(CHARGE=weight)"] if gravity else [])
    )
    return """
model = AFFE_MODELE(MAILLAGE=mesh, AFFE=_F(TOUT="OUI", PHENOMENE="MECANIQUE", MODELISATION="3D"))
material = DEFI_MATERIAU(ELAS=_F(E=%.10g, NU=%.10g, RHO=%.10g))
assigned = AFFE_MATERIAU(MAILLAGE=mesh, AFFE=_F(TOUT="OUI", MATER=material))
held = AFFE_CHAR_MECA(MODELE=model, DDL_IMPO=_F(GROUP_MA=%s, DX=0.0, DY=0.0, DZ=0.0))
%s%s
result = MECA_STATIQUE(MODELE=model, CHAM_MATER=assigned, EXCIT=(%s,))
result = CALC_CHAMP(reuse=result, RESULTAT=result, CONTRAINTE=("SIGM_NOEU",), CRITERES=("SIEQ_NOEU",))
ANSWER = {
    "displacement": nodal(result.getField("DEPL", 1), ["DX", "DY", "DZ"]),
    "von_mises": nodal(result.getField("SIEQ_NOEU", 1), ["VMIS"]),
}
""" % (
        float(request.get("youngs_modulus", 2.1e11)),
        float(request.get("poissons_ratio", 0.30)),
        density,
        aster.group_list(fixed),
        loads,
        weight,
        ", ".join(excitations),
    )


def _verdict(peak_stress, peak_displacement, request):
    """What the numbers mean, as findings: the thresholds the package configured."""
    findings = []
    yield_strength = float(request.get("yield_strength", 2.5e8))
    safety_factor = float(request.get("safety_factor", 1.5))
    allowable = yield_strength / max(safety_factor, 1e-9)
    if peak_stress > yield_strength:
        findings.append(
            {
                "severity": ERROR,
                "message": "The part yields under this load: peak stress %.3g MPa against a yield strength of %.3g MPa."
                % (peak_stress / 1e6, yield_strength / 1e6),
                "where": "peak von Mises stress",
            }
        )
    elif peak_stress > allowable:
        findings.append(
            {
                "severity": WARNING,
                "message": "The part does not reach the safety factor of %.2f: peak stress %.3g MPa against an "
                "allowable %.3g MPa." % (safety_factor, peak_stress / 1e6, allowable / 1e6),
                "where": "peak von Mises stress",
            }
        )
    limit = request.get("max_displacement")
    if limit is not None and peak_displacement > float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": "The part moves %.3g mm under this load, past the %.3g mm it is allowed."
                % (peak_displacement, float(limit)),
                "where": "peak displacement",
            }
        )
    return findings


# Importable as a module by its tests, and executed by PartCAD's meta-wrapper
# under the run name below -- so nothing here runs on import.
if __name__ == "__partcad_export__":
    pass

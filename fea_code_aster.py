#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae fea`, by Code_Aster: a linear static stress analysis of one part.

`fix:` holds the faces its ports cover still in every direction (`DDL_IMPO`);
`load:` spreads its force evenly over the faces its ports cover (`FORCE_FACE`):
along the direction the part states, a load written as `[x, y, z]` in its own
frame, and along -Z, where a weight goes, for a load written as a magnitude.
Gravity acts on the part's own mass too (`PESANTEUR`): the `gravity:` the part
states, in its own frame -- what a simulation found it under, `g - a` -- or
9.81 m/s^2 along -Z unless `self_weight` is off. `MECA_STATIQUE` solves it on
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
    gravity = _gravity_of(request)
    faces = []
    for name, record in zip(loaded, loaded_records):
        # A force on the port, spread over the area it covers: a traction, so a
        # finer mesh does not load the part harder.
        area = float(record["area"]) * aster.M2_PER_MM2
        components = ", ".join(
            "%s=%.10g" % (axis, value / area) for axis, value in zip(("FX", "FY", "FZ"), _force_of(record)) if value
        )
        faces.append("_F(GROUP_MA=%r, %s)" % (name, components or "FZ=0.0"))
    loads = "pulled = AFFE_CHAR_MECA(MODELE=model, FORCE_FACE=(%s,))\n" % ", ".join(faces) if faces else ""
    weight = (
        "weight = AFFE_CHAR_MECA(MODELE=model, PESANTEUR=_F(GRAVITE=%.10g, DIRECTION=(%.10g, %.10g, %.10g)))\n"
        % ((gravity[0],) + gravity[1])
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


def _force_of(record):
    """The force on one loaded port, newtons in the part's frame: as stated, or its magnitude straight down."""
    force = record.get("force")
    if isinstance(force, (list, tuple)) and len(force) == 3:
        return [float(component) for component in force]
    return [0.0, 0.0, -float(record["load"])]


def _gravity_of(request):
    """The gravity the part is weighed under, '(m/s^2, unit direction)', or None to weigh it not at all.

    The part's own `gravity:`, in its frame, where it stated one -- a gravity of
    nought weighs nothing; otherwise 9.81 m/s^2 along -Z when `self_weight` is
    on. `PESANTEUR` takes a magnitude and a direction, not a vector.
    """
    stated = request.get("gravity")
    if isinstance(stated, (list, tuple)) and len(stated) == 3:
        vector = [float(component) for component in stated]
        magnitude = sum(component * component for component in vector) ** 0.5
        if magnitude == 0.0:
            return None
        return magnitude, tuple(component / magnitude for component in vector)
    if request.get("self_weight", True):
        return 9.81, (0.0, 0.0, -1.0)
    return None


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

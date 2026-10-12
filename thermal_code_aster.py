#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae thermal`, by Code_Aster: steady heat conduction through one part.

`temperature:` holds the faces its ports cover at a temperature (`TEMP_IMPO`);
`heat:` puts a power in through them, spread over their area (`FLUX_REP`);
`convection:` cools them by the surrounding fluid against `ambient_temperature`
(`ECHANGE`). Every other surface is insulated. `THER_LINEAIRE` solves it, in
Celsius -- conduction and convection do not care where the zero is.
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
    held, held_records, held_empty = support.condition_groups(request, "temperature", "TEMP")
    heated, heated_records, heated_empty = support.condition_groups(request, "heat", "HEAT")
    cooled, cooled_records, cooled_empty = support.condition_groups(request, "convection", "CONV")
    findings.extend(aster.nothing_covered(record) for record in held_empty + heated_empty + cooled_empty)
    if not held_records and not cooled_records:
        raise support.ToolFailed(
            "'thermal:' gives the heat nowhere to go: hold a surface at a 'temperature:', or cool one by "
            "'convection:', on a port that covers a surface of the part. Without one there is no steady state"
        )

    with tempfile.TemporaryDirectory() as work:
        # A directory to keep the study in, for whoever is debugging one by hand.
        work = os.environ.get("PARTCAD_CODE_ASTER_STUDY") or work
        mesh = aster.mesh_part(request, {**held, **heated, **cooled}, work, int(request.get("mesh_order", 2)))
        answer = aster.run(work, _comm(request, held, held_records, heated, heated_records, cooled, cooled_records))

    temperature = [value[0] for value in answer["temperature"]]
    aster.draw(path, mesh, aster.by_position({**answer, "t": temperature}, "t", mesh))

    hottest, coldest = max(temperature), min(temperature)
    limit = request.get("max_temperature")
    if limit is not None and hottest > float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": "The part reaches %.4g C, past the %.4g C it may." % (hottest, float(limit)),
                "where": "hottest point",
            }
        )
    put_in = sum(float(record["heat"]) for record in heated_records)
    return {
        "success": True,
        "findings": findings,
        "warnings": [
            "Temperature from %.4g C to %.4g C, %.4g W put in, over %d elements"
            % (coldest, hottest, put_in, mesh.element_count)
        ],
    }


def _comm(request, held, held_records, heated, heated_records, cooled, cooled_records):
    ambient = float(request.get("ambient_temperature", 20.0))
    keywords = []
    if held:
        keywords.append(
            "TEMP_IMPO=(%s,)"
            % ", ".join(
                "_F(GROUP_MA=%r, TEMP=%.10g)" % (n, float(r["temperature"])) for n, r in zip(held, held_records)
            )
        )
    if heated:
        keywords.append(
            "FLUX_REP=(%s,)"
            % ", ".join(
                "_F(GROUP_MA=%r, FLUN=%.10g)" % (n, float(r["heat"]) / (float(r["area"]) * aster.M2_PER_MM2))
                for n, r in zip(heated, heated_records)
            )
        )
    if cooled:
        keywords.append(
            "ECHANGE=(%s,)"
            % ", ".join(
                "_F(GROUP_MA=%r, COEF_H=%.10g, TEMP_EXT=%.10g)" % (n, float(r["convection"]), ambient)
                for n, r in zip(cooled, cooled_records)
            )
        )
    return """
model = AFFE_MODELE(MAILLAGE=mesh, AFFE=_F(TOUT="OUI", PHENOMENE="THERMIQUE", MODELISATION="3D"))
material = DEFI_MATERIAU(THER=_F(LAMBDA=%.10g, RHO_CP=%.10g))
assigned = AFFE_MATERIAU(MAILLAGE=mesh, AFFE=_F(TOUT="OUI", MATER=material))
conditions = AFFE_CHAR_THER(MODELE=model, %s)
# A steady state is one instant, and THER_LINEAIRE asks for a list of them
# whatever it is solving.
instants = DEFI_LIST_REEL(VALE=(0.0,))
result = THER_LINEAIRE(
    MODELE=model,
    CHAM_MATER=assigned,
    EXCIT=_F(CHARGE=conditions),
    TYPE_CALCUL="STAT",
    INCREMENT=_F(LIST_INST=instants),
)
ANSWER = {"temperature": nodal(result.getField("TEMP", 1), ["TEMP"])}
""" % (
        float(request.get("conductivity", 50.0)),
        float(request.get("density", 7850)) * float(request.get("specific_heat", 490.0)),
        ", ".join(keywords),
    )


# Importable as a module by its tests, and executed by PartCAD's meta-wrapper
# under the run name below -- so nothing here runs on import.
if __name__ == "__partcad_export__":
    pass

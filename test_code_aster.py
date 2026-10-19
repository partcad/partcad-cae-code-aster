#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What can be checked about this package, with and without Code_Aster in the room.

Without it: the command files each analysis writes, the join between Code_Aster's
nodes and gmsh's, and that a machine with no Code_Aster is told what to do.

With it -- in this package's image, or on a workstation with Code_Aster, gmsh and
build123d -- the example cantilever is analysed three ways and compared with its
closed forms.

Run with `pytest` from this directory, beside an installed `partcad` (for the
sandbox helpers the scripts import; see `conftest.py`).
"""

import math
import os

import numpy
import pytest

support = pytest.importorskip("cae_support", reason="needs a partcad with wrappers/cae_support.py")

import code_aster_common as aster  # noqa: E402
import dynamic_code_aster  # noqa: E402
import fea_code_aster  # noqa: E402
import thermal_code_aster  # noqa: E402


def test_a_machine_with_no_code_aster_is_told_what_to_install(monkeypatch):
    monkeypatch.delenv(aster.RUN_ASTER_ENV, raising=False)
    monkeypatch.setattr(aster.shutil, "which", lambda _name: None)
    monkeypatch.setattr(aster, "DIRECTORIES", ())
    monkeypatch.setattr(aster.sys, "prefix", "/nonexistent")
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    with pytest.raises(support.ToolMissing) as raised:
        aster.find_run_aster()
    message = str(raised.value)
    assert "dockerImage:" in message
    assert "conda install -c conda-forge code-aster" in message
    assert aster.RUN_ASTER_ENV in message


def test_fields_are_joined_to_the_mesh_by_position():
    class Mesh:
        coordinates = numpy.array([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.0, 0.1, 0.0]])
        extent = 0.1

    # Code_Aster's own order, printed to fewer digits.
    answer = {"coordinates": [[0.1, 0.0, 0.0], [0.0, 0.1000000001, 0.0], [0.0, 0.0, 0.0]], "t": [1.0, 2.0, 3.0]}
    assert aster.by_position(answer, "t", Mesh()) == [3.0, 1.0, 2.0]


def test_a_load_is_a_face_force_along_minus_z():
    comm = fea_code_aster._comm({"self_weight": False}, {"FIX0": [1]}, {"LOAD0": [2]}, [{"load": 100.0, "area": 100.0}])
    assert "FORCE_FACE=(_F(GROUP_MA='LOAD0', FZ=-1000000),)" in comm
    assert "DDL_IMPO=_F(GROUP_MA=('FIX0'), DX=0.0, DY=0.0, DZ=0.0)" in comm
    assert "PESANTEUR" not in comm


def test_a_load_with_a_direction_is_a_face_force_along_it():
    comm = fea_code_aster._comm(
        {"self_weight": False}, {"FIX0": [1]}, {"LOAD0": [2]}, [{"load": 5.0, "force": [3.0, 0.0, -4.0], "area": 1.0}]
    )
    # 3 N and -4 N over 1 mm^2; nothing along Y, so no FY at all.
    assert "FORCE_FACE=(_F(GROUP_MA='LOAD0', FX=3000000, FZ=-4000000),)" in comm


def test_the_part_is_weighed_under_the_gravity_it_states():
    comm = fea_code_aster._comm({"gravity": [0.0, -6.0, -8.0]}, {"FIX0": [1]}, {}, [])
    assert "PESANTEUR=_F(GRAVITE=10, DIRECTION=(0, -0.6, -0.8))" in comm
    assert "_F(CHARGE=weight)" in comm
    # Nought weighs nothing; no gravity stated is 9.81 down -Z.
    assert "PESANTEUR" not in fea_code_aster._comm({"gravity": [0, 0, 0]}, {"FIX0": [1]}, {}, [])
    assert "GRAVITE=9.81, DIRECTION=(0, 0, -1)" in fea_code_aster._comm({}, {"FIX0": [1]}, {}, [])


def test_the_fea_file_type_says_it_reads_a_direction_and_a_gravity():
    import yaml

    with open(os.path.join(os.path.dirname(__file__), "partcad.yaml"), encoding="utf-8") as f:
        declared = yaml.safe_load(f)["cae"]["fea"]
    assert sorted(declared["reads"]) == ["force", "gravity"]


def test_the_modal_study_asks_for_the_lowest_modes():
    comm = dynamic_code_aster._comm({}, {"FIX0": [1]}, 4)
    assert 'OPTION="PLUS_PETITE", CALC_FREQ=_F(NMAX_FREQ=4)' in comm


def test_the_thermal_study_holds_heats_and_cools():
    comm = thermal_code_aster._comm(
        {"ambient_temperature": 25.0},
        {"TEMP0": [1]},
        [{"temperature": 20.0}],
        {"HEAT0": [2]},
        [{"heat": 1.0, "area": 100.0}],
        {"CONV0": [3]},
        [{"convection": 10.0}],
    )
    assert "TEMP_IMPO=(_F(GROUP_MA='TEMP0', TEMP=20),)" in comm
    assert "FLUX_REP=(_F(GROUP_MA='HEAT0', FLUN=10000),)" in comm
    assert "ECHANGE=(_F(GROUP_MA='CONV0', COEF_H=10, TEMP_EXT=25),)" in comm
    assert 'TYPE_CALCUL="STAT"' in comm


def test_nothing_held_is_said_rather_than_solved():
    for module in (fea_code_aster, dynamic_code_aster):
        result = module.process("/nonexistent.glb", {"boundary": []})
        assert result["success"] is False and "holds nothing" in result["exception"]


def _here():
    try:
        aster.find_run_aster()
        return True
    except support.ToolMissing:
        return False


needs_code_aster = pytest.mark.skipif(not _here(), reason="needs Code_Aster")


def _cantilever(analysis):
    build123d = pytest.importorskip("build123d")
    pytest.importorskip("gmsh")
    root = {"port": "root", "location": [[-50, 0, 0], [0, 0, 1], 0]}
    tip = {"port": "tip", "location": [[50, 0, 0], [0, 0, 1], 0]}
    boundary = {
        "fea": [dict(root, fix=True, load=0.0), dict(tip, fix=False, load=100.0)],
        "dynamic": [dict(root, fix=True)],
        "thermal": [
            dict(root, temperature=20.0, heat=None, convection=None),
            dict(tip, temperature=None, heat=1.0, convection=None),
        ],
    }[analysis]
    request = {
        "analysis": analysis,
        "wrapped": build123d.Box(100, 10, 10).wrapped,
        "boundary": boundary,
        "youngs_modulus": 2.0e11,
        "poissons_ratio": 0.3,
        "density": 7850,
        "self_weight": False,
        "mesh_size": 0.03,
        "mesh_order": 2,
        "conductivity": 50.0,
        "modes": 2,
    }
    assert support.prepare(request) == []
    return request


@needs_code_aster
def test_the_cantilever_deflects_as_a_beam(tmp_path):
    result = fea_code_aster.process(str(tmp_path / "c.glb"), _cantilever("fea"))
    assert result["success"], result.get("exception")
    deflection = float(result["warnings"][0].split("peak displacement ")[1].split()[0])
    assert deflection == pytest.approx(0.2016, rel=0.01)


@needs_code_aster
def test_the_cantilever_rings_as_a_beam(tmp_path):
    result = dynamic_code_aster.process(str(tmp_path / "c.glb"), _cantilever("dynamic"))
    assert result["success"], result.get("exception")
    first = float(result["warnings"][0].split("Natural frequencies ")[1].split(",")[0])
    expected = 1.875104**2 / (2 * math.pi * 0.1**2) * math.sqrt(2.0e11 * 0.01**4 / 12 / (7850 * 1e-4))
    assert first == pytest.approx(expected, rel=0.01)


@needs_code_aster
def test_the_cantilever_warms_as_a_rod(tmp_path):
    result = thermal_code_aster.process(str(tmp_path / "c.glb"), _cantilever("thermal"))
    assert result["success"], result.get("exception")
    hottest = float(result["warnings"][0].split(" C to ")[1].split(" C")[0])
    assert hottest == pytest.approx(40.0, rel=1e-3)

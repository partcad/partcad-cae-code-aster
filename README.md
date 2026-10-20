# partcad-cae-code-aster

Static stress, modal and steady heat transfer analysis for [PartCAD](https://github.com/partcad/partcad), by
[Code_Aster](https://www.code-aster.org/), EDF's structural and thermal solver.

```shell
pc cae fea -i //pub/feature/cae/code_aster:fea :bracket
pc cae dynamic -i //pub/feature/cae/code_aster:dynamic :bracket
pc cae thermal -i //pub/feature/cae/code_aster:thermal :heatsink
```

or name it for a part with `implementation:` in the part's analysis section, or for everything with the
`caeFeaImplementation`, `caeDynamicImplementation` and `caeThermalImplementation` user configuration options.

There is no `cfd` here: Code_Aster has no viscous flow solver. EDF's is code_saturne -- see
[partcad-cae-code-saturne](https://github.com/partcad/partcad-cae-code-saturne).

## What each analysis reads

Every key names interfaces the part implements, and is applied to the **faces each port covers**: PartCAD
imprints a port's sketch on the part before this package runs; a port with no sketch covers the face it lies
on.

| analysis | section keys | Code_Aster |
| --- | --- | --- |
| `fea` | `fix:`, `load:`, `gravity:` | `DDL_IMPO` on every displacement; `FORCE_FACE`, the force over the faces' area, along the direction the part states (`[x, y, z]` in its frame) or along -Z for a magnitude; `PESANTEUR` for the part's own weight, under the `gravity:` it states or 9.81 m/s² along -Z; `MECA_STATIQUE` |
| `dynamic` | `fix:` | `DDL_IMPO`; stiffness and mass assembled; `CALC_MODES` for the lowest `modes` |
| `thermal` | `temperature:`, `heat:`, `convection:` | `TEMP_IMPO` (C); `FLUX_REP`, the power over the faces' area; `ECHANGE` against `ambient_temperature`; `THER_LINEAIRE`, steady. Every other surface is insulated |

### What the numbers mean

A `load` value is a force, and PartCAD turns it into newtons before this package sees it. Write a number and a
unit -- `n`, `mn`, `kn` or `newton` for a force, `mg`, `g`, `kg`, `ton`, `tonne`, `lb` or `pound` for a mass,
matched case-insensitively, with or without a space and a plural `s` -- or a **bare number, which is a mass in
kilograms**, weighed at 9.8 N/kg: `hook: 5` is 49 N. A direction is three of those, each read the same way, so
`[0, 0, -5]` is the same 49 N straight down, and `[0 N, -2.7 N, -155.2 N]` is newtons as written. What a
simulation measured is in newtons, so write the unit: `[0, -2.7, -155.2]` would be read as 1.5 kN.

`gravity:` is an acceleration, m/s² along each of the part's axes -- a number, or a string saying so
(`9.81 m/s^2`). The part's own weight, its `density` times its volume, is taken under it instead of the
9.81 m/s² along -Z that `self_weight` applies otherwise; a part's own weight is never a `load`.

The model is `<part>.<analysis>.glb`, coloured by von Mises stress, by the first mode's displacement, or by
temperature. A measurement line goes to the log, and **findings** fail `pc test`: a stress past the yield
strength (or past it divided by `safety_factor`), a displacement past `max_displacement`, a first natural
frequency under `min_frequency`, a temperature past `max_temperature`, and any condition whose port covers no
surface.

### The pipeline

gmsh meshes the part into quadratic tetrahedra and writes it as MED, each condition's faces a named group
(PartCAD's `cae_support.mesh()`). The script writes the command file; `run_aster` runs the study; the study
ends by writing what it computed -- every node's position and the field asked for, the frequencies -- as JSON,
which is read back and joined to gmsh's nodes by position.

### Measured

`examples/feature_cae` in the PartCAD repository has a cantilever whose answers are formulas. Through
`pc cae`, in the image:

| analysis | closed form | this package |
| --- | --- | --- |
| `fea`: tip deflection, 100 N on a 100x10x10 mm steel bar | 0.2016 mm (with shear) | 0.2005 mm |
| `dynamic`: first bending frequency | 815.4 Hz (Euler-Bernoulli) | 813.25 Hz, twice -- the square section's two bending planes |
| `thermal`: hottest point, 1 W at the tip, root at 20 C | 40.0 C | 40.0 C |

Elmer, on the same mesh, gives the same displacement, frequencies and temperatures to every printed digit.

## What it needs

**A container runtime on x86_64, or Code_Aster installed.**

With a container runtime PartCAD runs the analyses in the image `partcad.yaml` names: PartCAD's Python base
image with conda-forge's Code_Aster in a prefix of its own. **amd64 only**: conda-forge builds Code_Aster for
64-bit x86 Linux and Windows, and nothing official exists for 64-bit ARM Linux.

Without one, PartCAD runs them in a conda or venv sandbox on the host, and Code_Aster has to be there.
`run_aster` is found, in this order, where `PARTCAD_CODE_ASTER` points, on `PATH`, in the sandbox's own conda
environment, and in `/opt/code_aster/bin`, `/opt/aster/bin`, `/usr/local/bin`, `~/code_aster/bin`. The easiest
way to have it is `conda install -c conda-forge code-aster`, on Linux and on Windows.

The daemon is what runs the analysis, so a variable set in your shell reaches it only when the daemon is
started from that shell: `pc daemon stop` first.

gmsh comes from pip, deliberately: Code_Aster reads MED, and pip's gmsh writes MED where a distribution's
often does not.

### The pin

`dockerImage:` names the image by a hash of what it is built from -- the Dockerfile, `verify_image.py` and the
Python version. Run `./image-tag.sh` after changing any of them and update every pin; the `Image` workflow
refuses to build if they disagree, and publishes `<tag>-amd64` on a push to `main`.

## Tests

```shell
pytest
```

beside an installed `partcad`. The command files, the join between Code_Aster's nodes and gmsh's, and the
messages a machine without Code_Aster gets are checked everywhere; the cantilever is analysed three ways and
compared with its closed forms where Code_Aster, gmsh and build123d are all present.

To keep a study for inspection, set `PARTCAD_CODE_ASTER_STUDY` to an empty directory before the daemon
starts.

## License

Apache License 2.0. Code_Aster is GPL-3.0 and is not part of this package: the image installs conda-forge's
build of it, whose recipe and sources are published by conda-forge.

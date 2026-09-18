#!/usr/bin/env python3
"""Reduce the reference anthropometric model to a browser-sized morph asset.

The upstream project solves a sparse deformation-to-vertex system at runtime
with SciPy. That is a good research/demo architecture, but it is not a useful
browser dependency. This one-time converter preserves its global learned
mapping by solving the reference system for a zero vector and each of the 19
measurement directions, then writing the resulting affine vertex bases as
Float32 data for WebGL.

Run from ``rag/`` after cloning the reference repository::

    python webapp/build_body_model_assets.py \
      --release-model /path/to/3D-Human-Body-Shape/release_model \
      --output webapp/static/body_model_mesh.bin
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np
import scipy.sparse
import scipy.sparse.linalg


V_NUM = 12_500
F_NUM = 25_000
M_NUM = 19
MAGIC = b"HC3D"
VERSION = 1


def _synthesize(factor, matrix: np.ndarray) -> np.ndarray:
    """Solve the upstream sparse system and return centered vertices."""
    rhs = factor.solve(matrix)
    vertices = rhs[: V_NUM * 3, :].reshape(V_NUM, 3, matrix.shape[1])
    vertices -= vertices.mean(axis=0, keepdims=True)
    return vertices.transpose(2, 0, 1)


def _load_sparse(path: Path) -> scipy.sparse.csc_matrix:
    loaded = np.load(path)
    return scipy.sparse.coo_matrix(
        (loaded["data"], (loaded["row"], loaded["col"])),
        shape=tuple(loaded["shape"]),
    ).tocsc()


def reduce_sex(release_model: Path, sex: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return means, stds, base vertices, and 19 vertex deformation bases."""
    prefix = release_model / f"{sex}_"
    d2v = _load_sparse(release_model / f"{sex}_d2v.npz")
    factor = scipy.sparse.linalg.splu((d2v.T @ d2v).tocsc())

    mean_deform = np.load(prefix.with_name(prefix.name + "mean_deform.npy"), mmap_mode="r")
    std_deform = np.load(prefix.with_name(prefix.name + "std_deform.npy"), mmap_mode="r")
    d_basis = np.load(prefix.with_name(prefix.name + "d_basis.npy"), mmap_mode="r")
    m2d = np.load(prefix.with_name(prefix.name + "m2d.npy"))
    mean_measure = np.load(prefix.with_name(prefix.name + "mean_measure.npy"))[:, 0]
    std_measure = np.load(prefix.with_name(prefix.name + "std_measure.npy"))[:, 0]

    zero_deform = np.asarray(mean_deform, dtype=np.float64).reshape(-1)
    deformation = np.empty((F_NUM * 9, M_NUM + 1), dtype=np.float64)
    deformation[:, 0] = zero_deform
    for index in range(M_NUM):
        # mapping_global() in the reference implementation applies m2d to the
        # normalized 19-measure vector before applying d_basis and std_deform.
        direction = np.asarray(d_basis @ m2d[:, index]).reshape(F_NUM, 9)
        deformation[:, index + 1] = (direction * std_deform + mean_deform).reshape(-1)

    vertices = _synthesize(factor, d2v.T @ deformation)
    base = vertices[0].astype(np.float32)
    bases = (vertices[1:] - vertices[0]).astype(np.float32)
    return mean_measure.astype(np.float32), std_measure.astype(np.float32), base, bases


def write_asset(release_model: Path, output: Path) -> None:
    # The released topology follows the upstream OBJ convention (1-based
    # indices); WebGL element arrays are 0-based.
    facets = (np.load(release_model / "facets.npy") - 1).astype(np.uint32)
    if facets.shape != (F_NUM, 3):
        raise ValueError(f"Unexpected facets shape: {facets.shape}")

    reduced = [reduce_sex(release_model, sex) for sex in ("female", "male")]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        # magic, version, vertices, faces, measurements, sex models
        handle.write(struct.pack("<6I", int.from_bytes(MAGIC, "little"), VERSION, V_NUM, F_NUM, M_NUM, 2))
        for means, stds, base, bases in reduced:
            np.asarray(means, dtype="<f4").tofile(handle)
            np.asarray(stds, dtype="<f4").tofile(handle)
            np.asarray(base, dtype="<f4").tofile(handle)
            np.asarray(bases, dtype="<f4").tofile(handle)
        np.asarray(facets, dtype="<u4").tofile(handle)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_asset(args.release_model, args.output)
    print(f"wrote {args.output} ({args.output.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()

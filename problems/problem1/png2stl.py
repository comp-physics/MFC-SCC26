#!/usr/bin/env python3
"""
Convert the opaque region of a transparent PNG into a flat (z = 0) ASCII STL for MFC 2D
STL patches (`stl_models(k)%model_filepath`).

MFC finds a 2D model's outline as the triangle edges used by exactly one triangle and
tests inside/outside with a winding number over those edges, so the mesh written here is
a conforming triangulation (no T-junctions) whose triangles all wind counter-clockwise.
Holes are supported. The model is scaled to fit within --width x --height (aspect ratio
kept) and its bounding box is centered at the origin.

Run with MFC's Python from the repository root, e.g.
  build/venv/bin/python runScripts/problem1/png2stl.py runScripts/problem1/logo.png runScripts/problem1/logo.stl
"""

import argparse
import sys

import numpy as np
from matplotlib.path import Path
from PIL import Image
from scipy.spatial import Delaunay
from skimage.measure import approximate_polygon, find_contours


def load_mask(path, threshold):
    img = Image.open(path)
    if "A" not in img.getbands() and "transparency" not in img.info:
        sys.exit(f"png2stl: {path} has no alpha channel; the opaque pixels define the shape.")
    alpha = np.asarray(img.convert("RGBA"))[:, :, 3]
    return np.pad(alpha >= threshold, 1)  # transparent border so every outline closes


def outlines(mask, tolerance, min_area):
    """Closed polygons (x right, y up, pixel units) around the opaque regions and holes."""
    polys = []
    for raw in find_contours(mask.astype(float), 0.5):
        c = approximate_polygon(raw, tolerance) if tolerance > 0 else raw
        xy = np.column_stack([c[:, 1], -c[:, 0]])[:-1]  # drop repeated closing point
        area = 0.5 * abs(np.dot(xy[:, 0], np.roll(xy[:, 1], -1)) - np.dot(xy[:, 1], np.roll(xy[:, 0], -1)))
        if len(xy) >= 3 and area >= min_area:
            polys.append(xy)
    if not polys:
        sys.exit("png2stl: no opaque region found (check --threshold / --min-area).")
    return polys


def triangulate(polys, max_iter=50):
    """Conforming Delaunay triangulation of the polygons' interior, all triangles CCW."""
    pts = np.vstack(polys)
    segs, start = [], 0
    for p in polys:
        idx = np.arange(start, start + len(p))
        segs += list(zip(idx, np.roll(idx, -1)))
        start += len(p)

    # Split boundary segments that Delaunay does not recover until all of them are edges.
    for _ in range(max_iter):
        tri = Delaunay(pts)
        edges = {tuple(sorted(e)) for s in tri.simplices for e in ((s[0], s[1]), (s[1], s[2]), (s[2], s[0]))}
        missing = [s for s in segs if tuple(sorted(s)) not in edges]
        if not missing:
            break
        mids = np.array([(pts[i] + pts[j]) / 2 for i, j in missing])
        new = {s: len(pts) + k for k, s in enumerate(missing)}
        pts = np.vstack([pts, mids])
        segs = [part for s in segs for part in (((s[0], new[s]), (new[s], s[1])) if s in new else (s,))]
    else:
        sys.exit("png2stl: outlines intersect after simplification; lower --tolerance.")

    # Every triangle lies wholly inside or outside each outline, so test centroids (even-odd).
    simplices = tri.simplices
    centroids = pts[simplices].mean(axis=1)
    inside = np.zeros(len(simplices), dtype=bool)
    for p in polys:
        inside ^= Path(p).contains_points(centroids)
    simplices = simplices[inside]

    a, b, c = (pts[simplices[:, k]] for k in range(3))
    cw = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]) < 0
    simplices[cw] = simplices[cw][:, [0, 2, 1]]
    return pts, simplices


def fit(pts, width, height):
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    scale = min(width / (hi[0] - lo[0]), height / (hi[1] - lo[1]))
    return (pts - (lo + hi) / 2) * scale


def write_stl(path, name, pts, simplices):
    v = [f"{x:.9e} {y:.9e} 0.000000000e+00" for x, y in pts]  # identical text for shared vertices
    with open(path, "w") as f:
        f.write(f"solid {name}\n")
        for t in simplices:
            f.write("  facet normal 0 0 1\n    outer loop\n")
            f.writelines(f"      vertex {v[i]}\n" for i in t)
            f.write("    endloop\n  endfacet\n")
        f.write(f"endsolid {name}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="PNG with transparency; opaque pixels form the shape")
    ap.add_argument("output", help="output ASCII STL")
    ap.add_argument("--threshold", type=int, default=128, help="alpha (0-255) at or above which a pixel is solid [128]")
    ap.add_argument("--tolerance", type=float, default=0.75, help="outline simplification in pixels; 0 keeps every step [0.75]")
    ap.add_argument("--min-area", type=float, default=4.0, help="drop specks and holes smaller than this many pixels [4]")
    ap.add_argument("--width", type=float, default=2.0, help="maximum model width [2]")
    ap.add_argument("--height", type=float, default=1.0, help="maximum model height [1]")
    args = ap.parse_args()

    polys = outlines(load_mask(args.input, args.threshold), args.tolerance, args.min_area)
    pts, simplices = triangulate(polys)
    pts = fit(pts, args.width, args.height)
    write_stl(args.output, "png2stl", pts, simplices)

    lo, hi = pts.min(axis=0), pts.max(axis=0)
    print(f"{args.output}: {len(simplices)} triangles, {len(polys)} outline(s), extent {hi[0] - lo[0]:.4f} x {hi[1] - lo[1]:.4f}")
    if len(simplices) > 10000:
        print("png2stl: warning: MFC's 2D boundary search is quadratic in edges; raise --tolerance or shrink the image.")


if __name__ == "__main__":
    main()

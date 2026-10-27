# Optional statistical dependency notices

No third-party source files are vendored or modified in this delivery. The integration calls installed packages, whose distributions include their own licenses and notices. Preserve these when distributing an environment or binary product.

| Direct dependency | Tested version | License / source |
| --- | --- | --- |
| scikit-learn | 1.8.0 | BSD-3-Clause; https://github.com/scikit-learn/scikit-learn/tree/1.8.0 |
| arch | 8.0.0 | NCSA (installed distribution License-Expression); https://github.com/bashtage/arch/tree/v8.0.0 |
| NumPy | 2.3.5 | BSD-3-Clause with bundled component notices; https://github.com/numpy/numpy/tree/v2.3.5 |
| SciPy | 1.17.0 | BSD-3-Clause with bundled component notices; https://github.com/scipy/scipy/tree/v1.17.0 |

`requirements-quant.txt` pins direct dependencies, not a complete transitive hash lock. Release packaging must inventory transitive licenses and platform-specific binary notices. LEAN has its own existing pinned-image boundary and Apache-2.0 upstream license. MLFinLab source is not included or used.

# SPDX-License-Identifier: MIT
"""Epitope benchmark construction.

This package turns the SAbDab2 summary table plus RCSB coordinates into a
shippable manifest of antibody-antigen instances with derived epitope labels.

It is deliberately separate from ``hotspot_preflight``: the library the user
installs must not depend on scipy, on network access, or on a pinned snapshot
of somebody else's database. Only the benchmark build does.

Install the extra deps with ``pip install -e '.[benchmark]'``.

The one thing to read before touching anything here is
``benchmark.epitope.epitope`` and the four guards it enforces. Every one of
them is a bug that silently produced plausible-looking wrong labels before it
was found, which is the worst failure mode a benchmark can have.
"""

__all__ = ["sabdab", "epitope", "cluster", "manifest"]

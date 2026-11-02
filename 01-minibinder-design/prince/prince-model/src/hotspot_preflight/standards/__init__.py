# SPDX-License-Identifier: MIT
"""Bridges to published synthetic-biology standards.

Two modules, two directions:

* :mod:`.sbol` — SBOL 3 in and out. The adapter that makes an SBOL ``Range``
  on a PDB-derived protein point at the residue it claims to, since ``Range``
  indexes the stored sequence string and author numbering does not. In: an
  expression construct supplies the crop for the burial check. Out: validated
  hotspots as ``SequenceFeature`` + ``Range``.
* :mod:`.rfc` — iGEM RFC 10 and RFC 1000. Reverse-translate a binder CDS that
  avoids the standard's illegal restriction sites, seams included.

:mod:`.sbol` needs the optional ``sbol3`` dependency, installed with the
``sbol`` extra. Importing it is safe without that dependency: the import is
deferred to the functions that serialise, and the numbering layer
(:func:`.sbol.sequence_index_map`, :func:`.sbol.chain_sequence`) works on
``gemmi`` alone.
"""

from __future__ import annotations

from . import rfc, sbol

__all__ = ["rfc", "sbol"]

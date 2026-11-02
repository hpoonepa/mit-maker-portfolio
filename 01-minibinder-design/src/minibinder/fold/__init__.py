"""Refold designed sequences independently and retain the predicted complexes.

The design loss already contains a contact term on the epitope indices, so a
good design score is partly circular evidence. An independent fold, audited for
actual heavy-atom contacts, is the only non-circular check that steering worked."""

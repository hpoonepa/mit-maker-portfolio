"""Turn an existing prediction into an inspectable author-residue document.

No reference annotations or model execution are involved. Missing apo residues
remain explicit, even if an ensemble proposal includes those sequence positions.
"""

from __future__ import annotations

from dataclasses import asdict

from .io import content_hash
from .mapping import ChainMapping
from .schema import Prediction, Target, require_indices


def prediction_document(target: Target, mapping: ChainMapping, prediction: Prediction) -> dict:
    if prediction.target_id != target.target_id or prediction.input_sha256 != content_hash(target):
        raise ValueError("Prediction belongs to a different input target/version")
    if (mapping.sequence, mapping.chain_id, mapping.model_index) != (
        target.sequence,
        target.chain_id,
        target.model_id,
    ):
        raise ValueError("Author mapping belongs to a different target")
    author = mapping.canonical_to_author
    sites = []
    for rank, site in enumerate(prediction.sites, 1):
        require_indices(site.residues, "export site residues", len(target.sequence))
        sites.append(
            {
                "rank": rank,
                **asdict(site),
                "residue_identifiers": [
                    {
                        "canonical_index_0based": index,
                        "sequence_position_1based": index + 1,
                        "amino_acid": target.sequence[index],
                        "apo_author_id": asdict(author[index]) if index in author else None,
                        "observed_in_apo": index in author,
                    }
                    for index in site.residues
                ],
            }
        )
    return {
        "schema_version": "1",
        "target_id": target.target_id,
        "apo_path": target.apo_path,
        "apo_sha256": target.apo_sha256,
        "author_mapping_sha256": content_hash(mapping),
        "prediction": {key: value for key, value in asdict(prediction).items() if key != "sites"},
        "sites": sites,
        "interpretation": "Ranked site hypotheses; scores are not calibrated binding probabilities.",
    }

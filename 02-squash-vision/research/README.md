# Local experiment helpers

The eighteen scripts in `helpers/` preserve local demo preparation and diagnostic work, including three nested personal-rally ball/contrast experiments. They expect the original media, cached models, saved match IDs and runtime layout. Read their input paths before running them: some import footage, schedule processing, pause jobs or restore cached artifacts. The nested experiments write diagnostic images/JSON beside their inputs.

The application runs independently of these helpers. Imported recordings, databases, downloaded weights, annotation archives and diagnostic outputs are omitted.

`local-notes/` preserves four historical run notes: professional-rally evidence, full-match verification, a personal-rally diagnostic and an annotation-archive audit. Their measurements are dated local evidence, not newly reproduced results. References to omitted files are retained as literal paths.

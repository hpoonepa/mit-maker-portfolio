# Contributing

Start with a small issue describing the input, observed result, and expected behavior. For a bug, include the relevant software version and a minimal public or synthetic example. Keep confidential structures and credentials out of issues.

Work on a branch and explain why the change is needed. Preserve third-party attribution and keep generated environments, caches, and large experiment outputs out of git.

## Before opening a merge request

Run `python -m pytest` and `python scripts/verify_artifacts.py`. For package changes, build a wheel and smoke-test its CLI from outside the source tree. For SBOL or CWL changes, install the corresponding optional validator and validate the produced document.

Scientific changes need an explicit description of the model, input population, metric, and control. Do not change split membership, label semantics, or a frozen artifact merely to make a test pass. New experimental results belong in a separately identified result directory with their own inputs and provenance.

A useful merge request explains the behavior before and after the change, the validation performed, and any limits that remain. Keep formatting-only changes separate from scientific logic when practical.

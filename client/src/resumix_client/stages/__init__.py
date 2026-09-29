"""``resumix watch``: a posting's four stages, and the folder each one lives in.

    1. analysis              --in           the file you dropped
    2. waiting for approval  working/       should_apply CHECK, until you answer
    3. waiting for the CV    working/       should_apply YES, or approved
    4. done                  cv/            generated (or re-rendered)
                             discarded/     should_apply NO, or you said d
                             error/         not a posting, or a call failed

Stage 1 runs on a thread of its own (:mod:`.inbox`), stage 3 on another
(:mod:`.generation`), and stage 2 is you, on the main thread
(:mod:`.approval`). Each stage takes one posting at a time; they run side by
side so a CV is written while you read the next posting. Every move between
stages is made by :class:`.working.WorkingProcessor`, under one lock, and a
folder goes where its own files say (:func:`.jobfolder.route`) — so a folder
left behind by a crash, or dropped back into ``--in`` from ``error/``, picks
up exactly where it stopped.

This package is its own line: it uses the shared modules (the API, the
workspace, the spreadsheet) but nothing of the older ``JobRunner`` pipeline
that ``clipboard`` and ``submit`` still run on.
"""

# data

Place the raw milking control files here (FULLSENSE `*.txt` exports from the milking robot).

The actual data files are **not committed** — they contain private farm data (national registration numbers) and are ignored by `.gitignore`. Only this README is tracked, so the folder exists on a fresh clone.

The uploader reads every `*.txt` file in this folder; see the column layout in [uploader/reference/scheme.json](../uploader/reference/scheme.json).

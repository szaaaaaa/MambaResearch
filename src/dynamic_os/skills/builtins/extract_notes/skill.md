Convert the supplied SourceSet into question-directed PaperNotes.

Send the full supplied document text, user request and node goal to the model; never silently take document prefixes. The shared request budget rejects oversized inputs before execution.

Return one note per source with source_id, a summary and verbatim evidence excerpts. Unknown sources, duplicate notes and fabricated excerpts fail validation. Preserve passage identifiers so downstream evidence maps and reports can trace claims. Indexing failure remains a warning; it does not discard the provided text.

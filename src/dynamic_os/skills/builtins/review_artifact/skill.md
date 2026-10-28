Review the ResearchReport input (or the first input artifact when there is no report) against the user request and original evidence.

NodeRunner attaches the run's sources, notes, evidence map, experimental results and clarified intent for both explicit and automatic review. Produce typed task_completed and claims_supported judgments plus the five existing scores. Accept only when both judgments pass and the weighted score reaches the threshold. A ResearchReport requires original SourceSet or ExperimentResults evidence; cautious wording alone does not establish evidence insufficiency.

Malformed assessments fail explicitly rather than becoming invented scores. A failed review can lead to evidence recovery before rewriting, within the existing planning and revision budgets.

Evidence is deduplicated only in the model input; original artifacts remain complete. Bind the verdict to the target artifact ID and payload SHA-256. Reuse an accepted review of that exact version; never reuse it after the report changes.

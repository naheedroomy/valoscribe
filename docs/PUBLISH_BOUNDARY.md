# Documentation and code-checkpoint publication boundary

This documentation records local VTA work and reviewed code checkpoints, but the presence of a document or its file paths does not establish that referenced code is included in a published checkout.

VTA-specific source, tests, scripts, configuration, assets, and optional dependencies may be local and uncommitted, or may be included in a checkout only as part of an explicitly enumerated, reviewed, dependency-complete code checkpoint. Check each checkpoint's allowlist and version/publication state before claiming code availability. This does not refer to the inherited upstream Valoscribe baseline. The six-file VTA-101 limited checkpoint described in [`vta101-code-checkpoint.md`](vta101-code-checkpoint.md) is version-specific: verify its referenced paths and checkpoint version in the checkout being described. The earlier docs-only commit `56e45e7` does not contain that checkpoint. Do not assert a push or other publication until verified against an actual commit SHA.

Commands, import snippets, file paths, and test recipes are scoped to the explicitly named local snapshot or checkpoint version. They may require code, dependencies, or local inputs not present in a docs-only checkout. Check the relevant evidence row and checkpoint for exact scope and source-media/fixture requirements. Do not imply that VTA implementation is universally absent from a future published checkout: only claim the code and dependencies actually included by its identified commit.

This notice describes publication boundaries only. It does not assert that any current uncommitted documentation or code has been pushed or published.

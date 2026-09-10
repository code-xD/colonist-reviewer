# Repository instructions

## Comment quality

Write code that explains itself through clear names, small functions, types, and
straightforward control flow. Do not add comments by default.

Add a comment or docstring only when it preserves information that the code cannot
express clearly, such as:

- why a non-obvious constraint or workaround exists;
- an invariant, security boundary, privacy boundary, or compatibility requirement;
- externally imposed behavior that would otherwise look accidental;
- a public API contract whose details are not evident from its signature.

Do not add comments that:

- narrate the next line or restate the code in English;
- label obvious sections or steps;
- repeat names, types, parameters, or return values;
- describe what changed instead of why the resulting code exists;
- contain generic filler, tutorial prose, or claims such as "robust", "clean", or
  "production-ready" without a concrete constraint;
- leave a `TODO`, `FIXME`, or speculative note without actionable context.

When editing existing code, preserve comments that document real constraints. Remove
stale or redundant comments in the lines you touch. Before finishing, inspect the diff
and delete every new comment that does not answer "why?", document a contract, or warn
about a genuine hazard.

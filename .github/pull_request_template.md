## What does this change?

<!-- One or two sentences. Link the issue it closes. -->

## Type of change

- [ ] feat: new feature
- [ ] fix: bug fix
- [ ] refactor: no behaviour change
- [ ] test: tests only
- [ ] docs: documentation only
- [ ] chore: tooling, dependencies, CI

## Trading safety checklist

- [ ] No strategy is claimed to be guaranteed profitable
- [ ] No look-ahead bias was introduced (indicators stay causal)
- [ ] The Risk Engine still has the final word before any order
- [ ] Orders are only created by the Execution Engine
- [ ] No API key or secret is logged, stored in plaintext or sent to the frontend
- [ ] Live trading remains disabled by default

## Verification

- [ ] `pytest` passes locally
- [ ] `ruff check .` passes
- [ ] `npm run lint` and `npm run typecheck` pass
- [ ] Tested in paper mode (describe what you observed)

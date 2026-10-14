---
description: Testing standards for test files
paths:
  - "tests/**"
  - "**/test_*.py"
  - "**/*_test.py"
  - "**/*.test.*"
  - "**/*.spec.*"
---

# Testing

- Write tests that verify behavior, not implementation details.
- Each test should have one clear assertion. Name it after what it proves.
- Test the public API of modules, not internal functions.
- Prefer fast unit tests on pure functions; keep a few integration tests for the pipeline end to end.
- Prefer real dependencies over mocks. Only mock external services (APIs, databases).
- Tests must never hit live external systems. Use fixtures or recorded samples.
- Cover edge cases of the domain: levels at or below zero (raw kept, cleaned floored), gaps, spikes, DST transitions, category boundaries.
- Every bug fix must include a regression test that fails without the fix.
- Run the full test suite before marking any task complete.

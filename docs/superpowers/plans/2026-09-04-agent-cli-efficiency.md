# Agent CLI Efficiency Implementation Plan

Goal: implement the user-approved compact outputs, structured errors, skill discovery, file inputs, Redis inspection and cursor continuation.
Architecture: shared CLI layer owns parsing, output and discovery. Database adapters retain their real backend. New Redis reads are CLI-specific extensions; existing MCP and page commands remain compatible.
Spec: approved six-point design in this task, including cursor compatibility and isolated write validation.

- [x] Add failing tests for output/error/input/discovery contracts; implement shared helpers and adapters.
- [x] Add Redis inspect and scan tests; implement bounded reads and lossless opaque continuation.
- [x] Shorten skills, move connection details to references, package both, align help.
- [x] Verify unit/CLI tests, installed commands, actual backend reads and isolated Redis test keys; record limitations.

Constraints: preserve unrelated work; keep normal metadata profile-only; no writes outside isolated test data; no automatic retry of ambiguous writes; no commits requested.

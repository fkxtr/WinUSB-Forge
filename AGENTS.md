# Working on WinUSB Forge

Read README.md, SECURITY.md and docs/architecture.md before changing disk operations.

- Work in the existing checkout. Cloud tasks already have isolated environments;
  do not create worktrees unless the user requests one.
- Never format, partition, mount for writing or change a real disk during development.
  Tests use temporary regular files and injected simulated device/command backends.
  Loop-device integration needs separate explicit authorization and disposable images.
- Keep read-only inspection separate from the privileged writer. No force, assume-yes
  or unattended flag may bypass live identity checks and typed confirmation.
- Revalidate disk identity before destructive commands. A pathname or serial alone
  does not identify a safe target. Preserve fail-closed behavior on incomplete data.
- Use subprocess argument lists, no shell interpolation. Keep external tools' failures
  and cleanup failures observable. A copied file does not establish durable success.
- Never download ISOs, proprietary drivers or bootloaders into the repository.
  Do not include credentials, private logs, serials or user content in fixtures.
- Dry-run may prepare a temporary local tree but must never write a block device,
  partition it, format it or mount it read-write.
- Every new disk-safety defect needs a regression test. Exercise failure recovery,
  hotplug changes, busy devices, copy interruption and cleanup errors.
- Run `python -m pytest`, `ruff check .`, `ruff format --check .`,
  `bandit -r src`, `mypy src --ignore-missing-imports`, and `python -m build`. Check installation in a fresh virtualenv.
- Update English and Spanish documentation together. Describe only implemented
  behavior and distinguish simulated tests, synthetic integration and real hardware.
- Keep the release preliminary until the documented hardware acceptance matrix has
  evidence. Never equate passing unit tests with a bootable Windows installer.

# Preparing a release

Use semantic versions with a prerelease suffix until the hardware acceptance
matrix has evidence. `0.1.0rc1` is a candidate, not a declaration that the product
is stable. Update the package version, displayed version and changelog together.

Before building an artifact:

1. Run tests, lint, formatting, Bandit and dependency auditing on the exact tree.
   Investigate failures; do not suppress them just to publish.
2. Review disk identity checks, confirmation, privilege boundaries, dry-run,
   interruption recovery, flush/readback and error-to-exit-status behavior.
3. Build with `python -m build`, install the wheel into a fresh virtualenv and
   execute help and documented read-only commands from outside the checkout.
4. Confirm sdist and wheel contain no ISO, driver, secret, user fixture or log.
5. Review English and Spanish docs against the actual command help. Record exact
   test counts and versions in release evidence, with skipped/unrun checks separate.
6. Obtain an independent maintainer review. Record hardware tests separately;
   incomplete hardware validation keeps the prerelease label.
7. Review Git changes, then push only with repository-owner authorization. The
   checked-in workflow builds candidate artifacts; it does not publish to PyPI or
   create a GitHub release automatically.

For an existing empty origin, after review and authorization, a maintainer can
publish the checkout using:

```sh
git add .
git commit -m "Implement WinUSB Forge 0.1.0rc1"
git branch -M main
git push -u origin main
```

These commands are instructions, not evidence that publication occurred. Review
`git status --short` and staged content first. Never force-push to resolve an
unexpected remote history.

## Español

Mantén el sufijo preliminar hasta completar la matriz física. Antes de publicar,
ejecuta pruebas, análisis, auditoría, construcción e instalación en un entorno
nuevo. Revisa identidad de disco, privilegios, confirmación, dry-run, recuperación
y sincronización. Examina el contenido de los paquetes para excluir medios
propietarios, secretos y registros. Revisa ambos idiomas contra la CLI real y
obtén una segunda revisión independiente. Registra pruebas físicas aparte.

La CI produce artefactos candidatos, pero no publica en PyPI ni crea releases.
Los comandos Git anteriores requieren revisión y autorización del propietario;
su presencia en la documentación no significa que se hayan ejecutado.

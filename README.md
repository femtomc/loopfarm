# loopfarm

Monitor-first autonomous loop runner.

## Migration Status

`loopfarm` is being migrated out of the workshop monorepo (`loopfarm/` path).

## History Strategy

To preserve package-local history during extraction:

```bash
# in workshop monorepo root
git subtree split --prefix=loopfarm -b loopfarm-export
git push https://github.com/femtomc/loopfarm.git loopfarm-export:main
```

## Compatibility Window

Legacy `ralph` aliases are temporarily supported during migration and are planned
for removal after **July 1, 2026**.

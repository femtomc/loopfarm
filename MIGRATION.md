# Loopfarm Package Notes

This package uses canonical Loopfarm naming as of **February 12, 2026**.

## Canonical Names

- Package directory: `loopfarm/`
- Python module: `loopfarm`
- CLI entrypoints: `loopfarm`, `loopfarm-format`, `loopfarm-monitor`
- Environment variables: `LOOPFARM_*`
- Forum topics and schemas: `loopfarm:*`, `loopfarm.*`

## Repository

Public repository: `https://github.com/femtomc/loopfarm`

History-preserving export flow from monorepo:

```bash
# In workshop monorepo root
git subtree split --prefix=loopfarm -b loopfarm-export
git push https://github.com/femtomc/loopfarm.git loopfarm-export:main
```

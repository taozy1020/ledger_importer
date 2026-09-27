# Third-party notices

This project contains original code licensed under Apache-2.0. It also
depends on third-party packages whose licenses remain their own.

The runtime dependency set includes:

- **Beancount**: GPL-2.0-or-later, as declared by the package metadata.
- **Beangulp**: GPL-2.0, as declared by the package metadata.

The optional Fava development/integration dependency is MIT-licensed. Other
transitive dependencies may have their own licenses; the exact locked set is
recorded in `uv.lock` and can be exported with:

```sh
make export-runtime
```

When redistributing an installed or bundled environment, preserve the
applicable upstream license notices and comply with the licenses of all
included packages. This file is an inventory aid, not a replacement for the
license texts shipped by those packages.

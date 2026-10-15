# Anatomy geometry kit

The four files in `kit/` are unmodified build-time modules from
[wheresryan22/anatomy](https://github.com/wheresryan22/anatomy), pinned to
`e9488296a44211c42701ff71705b7901470ec78f`. `UPSTREAM.json` records SHA-256 for
each file and the preserved MIT license. `tube.mjs` is an audit dependency;
the rover figure itself has no rendered pipes or cables.

The rover layout in `scripts/build_rover_anatomy.mjs` is original illustrative
geometry. Its dimensions are drawing units, not a physical rover specification.
The 69 recorded solids map to 14 telemetry components. The kit's static depth
solver orders every overlapping solid; its audit checks the shapes actually
drawn. There is no exploded pose or moving geometry to audit.

Regenerate and audit from the repository root:

```bash
node scripts/build_rover_anatomy.mjs --audit
```

`web/rover-anatomy.js` is the committed result: static SVG plus the controller
from `scripts/rover_anatomy_runtime.js`. The browser does not import this kit,
install a package, fetch a model, or contact any external service. The generated
asset works with the existing plain JavaScript dashboard.

The optional `--preview` build writes dark and light verification pages to
`/tmp/rover-anatomy-{dark,light}.html`. Anatomy’s upstream capture and line-end
tools can inspect those pages when Chromium is installed. The upstream skill
recommends Node.js 20.10+ for its full tool collection; the core app retains its
existing Node.js 18+ verification requirement.

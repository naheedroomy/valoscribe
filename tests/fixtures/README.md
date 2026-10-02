# Synthetic CV fixtures

`generate_synthetic_frame.py` creates a 320×180 PNG containing three labeled,
solid-color square anchors on a black background plus machine-readable metadata.
The pixel and normalized coordinates are synthetic test geometry only; they are
not HUD crops, map coordinates, or production thresholds. The fixture is intended
for offline crop, coordinate-transform, and registration unit tests.

The semantic expected output is stored at `tests/expected/golden/` and compared
by `tests/test_fixture_conventions.py`. Tests generate assets under pytest's
temporary directory rather than checking generated binaries into Git. The
expected-output convention compares stable geometry, dimensions, colors, and
pixel samples; it excludes timestamps, machine-specific paths, and codec data.

No copyrighted VOD frames or external assets are included. The user-provided
1.8 GB Ascent VOD under the sibling `VOD/` directory is an external local input;
its redistribution rights have not been established, so it must not be copied
into this repository or used as a committed test fixture. Real-frame fixture
provenance and permission must be documented before adding any such asset.

Generate manually with:

```bash
uv run --offline python tests/fixtures/generate_synthetic_frame.py /tmp/valoscribe-fixture
```

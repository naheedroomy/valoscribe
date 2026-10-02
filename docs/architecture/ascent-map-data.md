# Ascent map data status

`src/valoscribe/config/ascent_map.json` records Ascent's stable map UUID and a
bundled canonical image. `geometry_status` remains `pending`: the partial site
highlight polygons below are observations about the image, not a complete or
validated tactical geometry.

The image is `src/valoscribe/config/maps/ascent_public_content_13_06.png`,
extracted from Riot's Public Content Catalog release 13.06 ZIP:
`https://valorant.dyn.riotcdn.net/x/content-catalog/PublicContentCatalog-release-13.06.zip`
ZIP member: `Maps/7EAECC1B-4337-BBF6-6AB9-04B8F06B3319.png`. Its SHA-256 is
`6094459e109b1f4e9d500277ebc4ce1392dd98fb4f2d92005be932105be8a593`; dimensions
are 2048x2048 RGBA. Riot's VALORANT Developer Portal describes the public
catalog assets as free to use. Follow Riot's current policies and attribution
requirements. Catalog release 13.06 identifies the catalog release, not a
verified game patch. The repository's MIT license covers project code, not Riot
assets. This is a fan project and is not endorsed or sponsored by Riot Games.

The two `site_polygons` are exact axis-aligned bounds of colored map-image
regions, measured from the bundled 2048x2048 image using pixel coordinates with
left/top inclusive and right/bottom exclusive: top `(551,162)-(726,444)` and
bottom `(426,1502)-(691,1745)`. Their normalized vertices are the corresponding
pixel-edge coordinates divided by 2048. They record only the colored asset
highlights, not confirmed playable/plantable extents. The top highlight aligns
with the A Site point and the bottom highlight with B Site under the community
API transform; this does not independently validate the transform or broadcast
orientation. They are deliberately named as highlights, not production site
regions.

No walkable-area mask, spawn polygons, named-zone polygons, or registered
broadcast orientation rule are asserted. No callout points are treated as zones.
The map schema prevents a definition marked validated from omitting required
geometry. Pending maps return no zone lookup results.

VTA-102 correspondence evidence is recorded in
`src/valoscribe/config/ascent_vta102_correspondence.json`. The source is a
community tactical overview at its recorded URL; it is not redistributed and
its machine-local copy is not part of the repository. Its SHA-256 and the
canonical image SHA-256 are checked by
`scripts/dev/diagnose_vta102_ascent_correspondence.py`, which fails closed if an
image is missing, changed, undecodable, or the wrong dimensions. A fresh,
read-only independent reviewer annotated six unique source-to-canonical pixel
pairs directly from the original images while blinded to the candidate matrix.
Those labels and uncertainty bounds are fixed and are not to be adjusted to
improve the result. The frozen candidate transform is evaluated using Euclidean
residual in canonical pixels, with allowed residual equal to source uncertainty
multiplied by transform scale plus target uncertainty. All six pass; maximum
residual is 7.79 px. This establishes point correspondence evidence only. It
does not validate silhouette boundaries, walls, occupancy, walkable space,
playable geometry, site/spawn polygon boundaries, or broadcast orientation.
`geometry_status` remains `pending`, and site and spawn polygons remain
untouched.

A separate metadata-only fixture,
`tests/fixtures/map_annotations/ascent-vta102-source-interior-v1.json`, preserves
the provisional VTA-102 label-site interior annotations against the same frozen
source/canonical hashes and correspondence-manifest hash. Six supplied
canonical-pixel rectangles have centers in the canonical alpha interior: A
Site, B Site, Defender Spawn, Attacker Spawn, Mid Courtyard, and B Main. The
supplied A Main rectangle is preserved only in `rejected_annotations`: its
exact center `(934, 410)` has alpha 0, so it is not an accepted sample. No
reviewer rectangle is treated as a boundary. `scripts/maintenance/validate_vta102_source_annotations.py`
provides opt-in source-image hash/dimension validation and fails closed if the
machine-local source image is absent; normal tests do not require that external
file.
This record does not change `ascent_map.json` or promote any zone lookup.

Remaining evidence required for production geometry: confirm asset/broadcast
orientation using permitted reference frames and the actual HUD profile; derive
and independently review a walkable mask, true site extents, both spawn regions,
and named-zone polygons; then measure registration confidence/error on held-out
frames and set thresholds from those results. Full VTA-102 acceptance is
pending. Do not promote this record to validated until those checks pass.

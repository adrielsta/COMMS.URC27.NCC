# Historical satellite basemap

The field and drone position maps display **real historical Sentinel-2 satellite
imagery**, bundled with the application for offline use. Positions, headings,
routes and other vehicle overlays remain simulated. The drone position map is a
map of the drone's reported coordinates; it is not a drone camera image.

## Source and permission

The source is [EOX::Maps](https://maps.eox.at/), using its **Sentinel-2 cloudless
2016** mosaic. EOX's [official WMTS capabilities](https://tiles.maps.eox.at/wmts/1.0.0/WMTSCapabilities.xml)
identify the selected layer `s2cloudless_3857` as “Sentinel-2 cloudless layer for
2016 by EOX - 3857.” Its abstract states:

> EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified
> Copernicus Sentinel data 2016) released under Creative Commons Attribution 4.0
> International License.

The license link in that same abstract is
<https://creativecommons.org/licenses/by/4.0/>. Preserve this attribution and
license when distributing the imagery:

**EOxCloudless by EOX IT Services GmbH (Contains modified Copernicus Sentinel data
2016), CC BY 4.0.** [EOX::Maps](https://maps.eox.at/) ·
[EOxCloudless](https://cloudless.eox.at/) ·
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

The nine JPEGs are original tile bytes from EOX, without image modifications,
stitching, enhancement or generated content. The UI resizes the tiles for display
and draws simulation overlays separately. The imagery's CC BY 4.0 terms remain
applicable separately from this repository's software license.

The layer and license were checked directly against the capabilities served over
verified HTTPS on **2026-10-13**. The captured capabilities SHA-256 and original
download URL, SHA-256 and byte length of every tile are recorded in
[`web/imagery/metadata.json`](../web/imagery/metadata.json). That digest identifies
the reviewed capabilities document; the provider can update its live document.
The 2017 layer advertised by the service returned blank images at this location,
so the verified 2016 layer is used. Later layers have different license terms;
do not assume that this license applies to a newer EOX mosaic.

## Geographic coverage and dates

The map covers the simulator's coordinates around MDRS in Utah. Its center is
**38.418° N, 110.777° W**. This location is a development default; it is not a
claim that the organizer has assigned the 2027 route or C2 location there.

| Property | Value |
| --- | --- |
| Source year | 2016 mosaic; exact per-pixel acquisition dates are not provided |
| Coordinate reference system | EPSG:3857, Web Mercator |
| EOX WMTS tile matrix | `g`, zoom 15, 256 × 256 pixel JPEGs |
| XYZ tile columns | 6299–6301 |
| XYZ tile rows | 12590–12592 |
| West / east edges | −110.797119140625° / −110.76416015625° |
| South / north edges | 38.40194908237822° / 38.42777351132903° |
| Image bundle size | 54,688 bytes in nine images |
| Source resolution | Nominal 10 m Sentinel-2 visible-band sampling; mosaic processing and display can reduce useful detail |

The service URL uses **row before column**:

```text
https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/15/{y}/{x}.jpg
```

The manifest uses conventional XYZ column `x` and row `y`, and local filenames
use `tile-{zoom}-{x}-{y}.jpg`. Geographic bounds are calculated from the outer
edges of those XYZ tiles; they are not manually stretched to match the simulated
route. At this latitude, a zoom-15 display pixel is approximately 3.7 m across;
oversampling does not create detail beyond the source imagery.

This old mosaic cannot establish current obstacles, safe paths, gradients,
landing sites or present field conditions. It is not live satellite imagery and
does not use satellite internet. The rules discussion and exact citations are
maintained in [requirements-matrix.md](requirements-matrix.md).

## Offline operation and verification

All images and metadata are served from the local C2 web server. Opening or
moving the maps needs no external map service, account, API key, CDN or internet
connection. External attribution links are navigation links for source review;
the browser does not fetch them to render the map.

From the repository root, verify the complete bundle without network access:

```bash
python3 scripts/fetch_imagery.py --verify
```

Restore missing files before going to the field:

```bash
python3 scripts/fetch_imagery.py
```

Existing files must match the manifest. The helper verifies SHA-256, byte size
and JPEG dimensions before accepting a file. Downloads have a timeout and size
limit, use HTTPS with certificate verification, and are restricted to the
reviewed `tiles.maps.eox.at` source. Redirects are rejected. `--refetch` downloads
again and requires the **same recorded hashes**; it never silently accepts a new
mosaic or updates provenance. The runtime does not invoke this helper.

If a published tile changes, review its source, location, dates and license in a
separate imagery update, then replace the bytes and metadata together. Do not
change a recorded hash solely to bypass a failed check. An area beyond this
small offline bundle requires another reviewed imagery bundle; it does not
trigger online tile requests.

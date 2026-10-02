# Sequential source-PTS reader

`SequentialPtsVideoSource` is an opt-in reader for local regular video files. It is separate from `VideoReader` and does not change legacy timestamp, seeking, sampling, or CLI behavior.

```python
from valoscribe.video.pts_reader import SequentialPtsVideoSource

with SequentialPtsVideoSource("local-vod.mp4") as source:
    print(source.metadata)
    for frame in source:
        # frame.frame_index is decode-output order; frame.source_pts is observed.
        # frame.timestamp_seconds is Fraction(PTS * time_base).
        frame.validate_against(source.metadata)
        consume(frame.bgr)
    assert source.complete_stream_verified
```

The metadata contract records rational nominal FPS and stream timebase, source dimensions, separately reported stream/container durations, ffprobe/ffmpeg version strings, and a local stat fingerprint. `SourceVideoFrame` carries the BGR array, zero-based sequential frame index, observed integer PTS, exact rational timebase and timestamp, and timestamp provenance (`pts` or explicitly `best_effort_timestamp`). No timestamp is synthesized from nominal FPS or frame index.

Before decoding, `ffprobe` inventories all selected `v:0` frame metadata. Missing, duplicate, nonmonotonic, mixed-provenance timestamps, changing dimensions, missing metadata, invalid clocks, or detected rotation fail closed. The ffmpeg process sequentially emits `bgr24` with passthrough timing and autorotation disabled; there is no seeking. The reader joins the two outputs by ordinal and checks early EOF, partial frames, extra decoded bytes, final process status, and source stat identity. Count/order agreement is only a decode-order join check: it does not prove pixel-to-PTS alignment independently.

`complete_stream_verified` remains false until the consumer advances through the entire stream and EOF, exact count, successful process exit, and unchanged stat fingerprint are all verified. Closing early releases the process and never certifies completion. Read, frame-validation, and final-stat exceptions close decoder resources while leaving completion false. A consumer must not certify finalized artifacts before this flag is true. `validate_against(metadata)` revalidates both frozen Pydantic contracts (including copied models), frame inventory bounds, and mutable array shape/type at the consumer boundary. No decoded-video arrays are retained, no artifacts are written, and no source hash is computed; source identity hashing belongs in the run manifest.

Requires `ffprobe` and `ffmpeg` already installed on `PATH`; the reader adds no package dependency or network use. It rejects an empty selected video stream and relies on ffprobe's full frame inventory in memory to validate timestamps before starting the decoder. stderr is drained into a bounded diagnostic tail; shutdown reaps the decoder and joins the drain thread before closing stderr or collecting final diagnostics. Container-specific rotation metadata outside the detected stream tag/side-data forms may need explicit handling before supporting such sources.

The next seam is a separately reviewed HUD-only source timeline using tournament coordinates only after they are independently verified for the actual VOD. This reader does not export HUD crops, define production coordinates, infer round boundaries, access protected source footage, or route a particular tracking model.

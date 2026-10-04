import assert from "node:assert/strict";
import { test } from "node:test";
import { limitOpenEndedRange, MAX_OPEN_RANGE_BYTES, parseRange } from "../lib/media-range";
import { isLoopbackHost, resolveAllowedFile } from "../lib/server";

test("parses bounded, open-ended and suffix media ranges", () => {
  assert.deepEqual(parseRange("bytes=4-9", 20), { start: 4, end: 9 });
  assert.deepEqual(parseRange("bytes=4-", 20), { start: 4, end: 19 });
  assert.deepEqual(parseRange("bytes=-4", 20), { start: 16, end: 19 });
  assert.deepEqual(parseRange("bytes=4-999", 20), { start: 4, end: 19 });
});

test("bounds open-ended media responses while preserving explicit ranges", () => {
  const range = parseRange("bytes=0-", 1_900_000_000);
  assert.notEqual(range, "invalid");
  assert.deepEqual(limitOpenEndedRange(range, "bytes=0-"), { start: 0, end: MAX_OPEN_RANGE_BYTES - 1 });
  assert.deepEqual(limitOpenEndedRange(parseRange("bytes=2-5", 20), "bytes=2-5"), { start: 2, end: 5 });
  assert.deepEqual(limitOpenEndedRange(parseRange("bytes=-4", 20), "bytes=-4"), { start: 16, end: 19 });
});

test("rejects malformed, multi-range and unsatisfiable byte ranges", () => {
  for (const header of ["items=1-2", "bytes=", "bytes=-0", "bytes=20-", "bytes=8-4", "bytes=1-2,4-5"]) {
    assert.equal(parseRange(header, 20), "invalid", header);
  }
  assert.equal(parseRange("bytes=0-", 0), "invalid");
  assert.equal(parseRange(null, 20), null);
});

test("loopback host validation rejects lookalikes", () => {
  assert.equal(isLoopbackHost("localhost:3000"), true);
  assert.equal(isLoopbackHost("127.0.0.1:3000"), true);
  assert.equal(isLoopbackHost("[::1]:3000"), true);
  assert.equal(isLoopbackHost("localhost.attacker.test:3000"), false);
  assert.equal(isLoopbackHost("0.0.0.0:3000"), false);
});

test("media resolver opens a real run MP4 and rejects traversal", async () => {
  const media = await resolveAllowedFile("ascent-team-movement-mvp002-r3/rounds/map3-round4/canonical_playback.mp4");
  assert.ok(media.size > 0);
  await assert.rejects(resolveAllowedFile("../VOD/source.mp4"), /Invalid media path/);
  await assert.rejects(resolveAllowedFile("%2e%2e/source.mp4"), /Invalid media path/);
});

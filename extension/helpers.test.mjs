import test from "node:test";
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {serverOrigin, pairingCode, authHeaders, permissionPattern} from "./helpers.mjs";

test("host permissions omit ports but destination retains them", () => {
  assert.equal(permissionPattern("http://localhost:8000"), "http://localhost/*");
  assert.equal(serverOrigin("http://localhost:8000"), "http://localhost:8000");
});

test("only HTTPS or explicit loopback HTTP destinations", () => {
  assert.equal(serverOrigin("https://example.com/"), "https://example.com");
  assert.equal(serverOrigin("http://127.0.0.1:8000"), "http://127.0.0.1:8000");
  for (const url of ["http://example.com", "https://user:pass@example.com", "https://example.com/path",
    "https://example.com/?code=secret", "https://example.com/#secret", "file:///tmp"]) {
    assert.throws(() => serverOrigin(url));
  }
});
test("codes have fixed entropy-bearing format", () => {
  assert.equal(pairingCode(" a" + "a".repeat(31) + " "), "a".repeat(32));
  assert.throws(() => pairingCode("123456"));
});
test("reconstructs hidden authorization without losing account selection", async () => {
  const cookie = "SID=unused; __Secure-3PAPISID=secret; SAPISID=primary";
  const auth = await authHeaders([
    {name: "Cookie", value: cookie}, {name: "X-Goog-AuthUser", value: "2"},
    {name: "X-Goog-PageId", value: "brand"}, {name: "Unrelated", value: "discard"}
  ], 1700000000000);
  const hash = createHash("sha1").update("1700000000 primary https://music.youtube.com").digest("hex");
  assert.deepEqual(auth, {cookie, authorization: `SAPISIDHASH 1700000000_${hash}`,
    "x-goog-authuser": "2", "x-goog-pageid": "brand"});
});
test("no logged-in cookie means no upload", async () => {
  assert.equal(await authHeaders([]), null);
  assert.equal(await authHeaders([{name: "Cookie", value: "SID=guest"}]), null);
});

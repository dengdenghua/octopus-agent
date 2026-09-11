import { afterEach, beforeEach, describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import runtime from "./opencode-runtime.cjs";

const require = createRequire(import.meta.url);
const lock = require("./opencode-runtime-lock.json");
const profile = lock.platforms["win32-x64"];
let resources;
let root;
let manifest;
const hash = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");

beforeEach(() => {
  resources = fs.mkdtempSync(path.join(os.tmpdir(), "echo-opencode-runtime-"));
  root = path.join(resources, "opencode");
  fs.mkdirSync(root);
  const license = fs.readFileSync(
    new URL(
      "../../extras/desktop/licenses/opencode-1.18.29/LICENSE",
      import.meta.url,
    ),
  );
  const files = {
    "opencode.exe": Buffer.from("MZ fixture"),
    LICENSE: license,
  };
  manifest = {
    schema: "echo.opencode_bundle.v1",
    version: lock.version,
    platform: "win32-x64",
    asset: profile.asset,
    archiveSha256: profile.sha256,
    executable: profile.executable,
    executableMagic: profile.executableMagic,
    fileHashPhase: profile.fileHashPhase,
    files: {},
  };
  for (const [name, bytes] of Object.entries(files)) {
    fs.writeFileSync(path.join(root, name), bytes);
    manifest.files[name] = hash(bytes);
  }
  writeManifest();
});

afterEach(() => fs.rmSync(resources, { recursive: true, force: true }));

function writeManifest() {
  fs.writeFileSync(
    path.join(root, "opencode-bundle.json"),
    JSON.stringify(manifest),
  );
}

describe("packaged OpenCode", () => {
  it("returns an absolute verified bundle path", () => {
    assert.equal(
      runtime.requirePackagedOpenCode(resources, "win32", "x64"),
      path.join(root, "opencode.exe"),
    );
  });
  for (const name of ["LICENSE"]) {
    it(`rejects corrupted ${name}`, () => {
      fs.appendFileSync(path.join(root, name), "tampered");
      assert.throws(
        () => runtime.requirePackagedOpenCode(resources, "win32", "x64"),
        /digest mismatch/,
      );
    });
  }
  it("rejects an executable with the wrong platform format", () => {
    fs.writeFileSync(path.join(root, "opencode.exe"), "not a PE executable");
    assert.throws(
      () => runtime.requirePackagedOpenCode(resources, "win32", "x64"),
      /format mismatch/,
    );
  });
  it("rejects a bundle for a different platform", () => {
    manifest.platform = "linux-x64";
    writeManifest();
    assert.throws(
      () => runtime.requirePackagedOpenCode(resources, "win32", "x64"),
      /provenance mismatch/,
    );
  });
  it("does not substitute PATH when a bundled binary is missing", () => {
    fs.unlinkSync(path.join(root, "opencode.exe"));
    assert.throws(
      () => runtime.requirePackagedOpenCode(resources, "win32", "x64"),
      /refusing PATH\/network fallback/,
    );
  });
  it("rejects changed release asset identity", () => {
    manifest.asset = "different-release-asset.zip";
    writeManifest();
    assert.throws(
      () => runtime.requirePackagedOpenCode(resources, "win32", "x64"),
      /provenance mismatch/,
    );
  });
  it("rejects files outside the signed inventory", () => {
    fs.writeFileSync(path.join(root, "unexpected"), "data");
    assert.throws(
      () => runtime.requirePackagedOpenCode(resources, "win32", "x64"),
      /inventory mismatch/,
    );
  });
});

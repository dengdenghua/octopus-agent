"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const lock = require("./opencode-runtime-lock.json");

function regularFile(root, name) {
  const file = path.join(root, name);
  const info = fs.lstatSync(file);
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new Error(`OpenCode resource is not a regular file: ${name}`);
  }
  return file;
}

function digest(file) {
  // Hash the native executable without allocating its entire size at startup.
  const hash = crypto.createHash("sha256");
  const buffer = Buffer.alloc(64 * 1024);
  const fd = fs.openSync(file, "r");
  try {
    let count;
    while ((count = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) {
      hash.update(buffer.subarray(0, count));
    }
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest("hex");
}

function readJson(file) {
  if (fs.statSync(file).size > 1024 * 1024) {
    throw new Error("OpenCode metadata exceeds size limit");
  }
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function requirePackagedOpenCode(
  resources,
  platform = process.platform,
  arch = process.arch,
) {
  const target = `${platform}-${arch}`;
  const profile = lock.platforms[target];
  if (!profile)
    throw new Error(`Unsupported packaged OpenCode platform: ${target}`);
  const root = path.resolve(resources, "opencode");
  try {
    const rootInfo = fs.lstatSync(root);
    if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink()) {
      throw new Error("OpenCode resource root is not a regular directory");
    }
    const manifest = readJson(regularFile(root, "opencode-bundle.json"));
    if (
      manifest.schema !== "echo.opencode_bundle.v1" ||
      manifest.version !== lock.version ||
      manifest.platform !== target ||
      manifest.asset !== profile.asset ||
      manifest.archiveSha256 !== profile.sha256 ||
      manifest.executable !== profile.executable ||
      manifest.executableMagic !== profile.executableMagic ||
      manifest.fileHashPhase !== profile.fileHashPhase
    ) {
      throw new Error("OpenCode bundle provenance mismatch");
    }
    const expectedFiles = [profile.executable, "LICENSE"];
    if (
      !manifest.files ||
      Object.keys(manifest.files).length !== expectedFiles.length ||
      !expectedFiles.every((name) =>
        Object.prototype.hasOwnProperty.call(manifest.files, name),
      )
    ) {
      throw new Error("OpenCode bundle file inventory mismatch");
    }
    const actualEntries = fs.readdirSync(root).sort();
    const allowedEntries = [...expectedFiles, "opencode-bundle.json"].sort();
    if (JSON.stringify(actualEntries) !== JSON.stringify(allowedEntries)) {
      throw new Error("OpenCode bundle file inventory mismatch");
    }
    for (const name of expectedFiles) {
      const expected = manifest.files?.[name];
      if (!/^[0-9a-f]{64}$/.test(expected || "")) {
        throw new Error(`OpenCode resource digest missing: ${name}`);
      }
      if (name === "LICENSE" && expected !== lock.license.sha256) {
        throw new Error("OpenCode license provenance mismatch");
      }
      const file = regularFile(root, name);
      if (name === profile.executable) {
        const header = Buffer.alloc(profile.executableMagic.length / 2);
        const descriptor = fs.openSync(file, "r");
        try {
          if (
            fs.readSync(descriptor, header, 0, header.length, 0) !==
              header.length ||
            header.toString("hex") !== profile.executableMagic
          ) {
            throw new Error("OpenCode executable format mismatch");
          }
        } finally {
          fs.closeSync(descriptor);
        }
      }
      // Windows and macOS packaging signs native executables after the source
      // manifest is written. CI verifies those signed artifacts separately.
      if (
        !(
          name === profile.executable && ["win32", "darwin"].includes(platform)
        ) &&
        digest(file) !== expected
      ) {
        throw new Error(`OpenCode resource digest mismatch: ${name}`);
      }
    }
    const executable = regularFile(root, profile.executable);
    if (platform !== "win32") fs.accessSync(executable, fs.constants.X_OK);
    return executable;
  } catch (error) {
    throw new Error(
      `Packaged OpenCode is unavailable; refusing PATH/network fallback: ${error.message}`,
    );
  }
}

module.exports = { requirePackagedOpenCode };

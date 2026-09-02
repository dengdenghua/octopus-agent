/**
 * Pet authoring sources that historically lived in `public/` as well as in
 * the canonical Godot project. The web UI does not reference these files, so
 * Vite may omit only the generated public copies after proving byte identity.
 */
export const WEB_BUILD_DEDUPLICATED_PET_ASSETS = [
  {
    publicPath: "assets/章鱼.fbx",
    canonicalPath: "../pet-sidecar/models/octopus/octopus.fbx",
  },
  {
    publicPath: "assets/character_rigged.glb",
    canonicalPath: "../pet-sidecar/models/character_rigged_clean.glb",
  },
] as const;

const AGENT_AVATAR_ASSET_VERSION = "pixel-halfbody-v3";

export function withAgentAvatarVersion(src: string): string {
  if (!src.includes("/api/agents/") || !src.includes("/avatar")) {
    return src;
  }
  if (src.includes("avatar_style=")) {
    return src;
  }
  const separator = src.includes("?") ? "&" : "?";
  return `${src}${separator}avatar_style=${AGENT_AVATAR_ASSET_VERSION}`;
}

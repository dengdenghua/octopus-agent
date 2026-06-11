from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from string import Template

AGENT_VISUAL_VIEWS = ("front", "side", "back")


@dataclass(frozen=True)
class AgentVisualResult:
    provider: str
    prompt: str
    files: dict[str, Path]


def build_agent_visual_prompt(
    *,
    agent_id: str,
    display_name: str,
    description: str = "",
    style_prompt: str = "",
) -> str:
    base = (
        "Generate a reusable 2D game/HUD agent character reference sheet, "
        "front view, side view, back view, dark sci-fi interface mood, "
        "neon yellow accents, clean full body character silhouettes, "
        "transparent or dark neutral background, premium RPG character profile style. "
        "Avoid 3D render, avoid wireframe, avoid rough sketch."
    )
    identity = f"Agent id: {agent_id}. Agent name: {display_name}."
    if description:
        identity += f" Description: {description[:500]}."
    if style_prompt:
        identity += f" Extra style: {style_prompt[:500]}."
    return f"{base} {identity}"


def generate_agent_visuals(
    *,
    agent_id: str,
    display_name: str,
    description: str,
    output_dir: Path,
    style_prompt: str = "",
    provider: str | None = None,
) -> AgentVisualResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_provider = (provider or os.getenv("OCTOPUS_IMAGE_GEN_PROVIDER") or "mock").strip()
    prompt = build_agent_visual_prompt(
        agent_id=agent_id,
        display_name=display_name,
        description=description,
        style_prompt=style_prompt,
    )

    if resolved_provider in {"mock", "local-mock"}:
        return _generate_mock_visuals(
            provider=resolved_provider,
            prompt=prompt,
            agent_id=agent_id,
            display_name=display_name,
            output_dir=output_dir,
        )
    if resolved_provider in {"opencli-jimeng", "jimeng-cli", "custom-command"}:
        return _generate_with_command(
            provider=resolved_provider,
            prompt=prompt,
            agent_id=agent_id,
            display_name=display_name,
            output_dir=output_dir,
        )
    raise ValueError(f"unsupported image generation provider: {resolved_provider}")


def _generate_with_command(
    *,
    provider: str,
    prompt: str,
    agent_id: str,
    display_name: str,
    output_dir: Path,
) -> AgentVisualResult:
    command_template = os.getenv("OCTOPUS_IMAGE_GEN_COMMAND")
    if not command_template and provider == "opencli-jimeng":
        command_template = 'opencli jimeng generate --prompt "$prompt" --output "$output"'
    if not command_template:
        raise RuntimeError(
            "OCTOPUS_IMAGE_GEN_COMMAND is required for this image provider"
        )

    output = output_dir / "reference.png"
    variables = {
        "agent_id": agent_id,
        "display_name": display_name,
        "prompt": prompt,
        "output": str(output),
        "output_dir": str(output_dir),
    }
    command = Template(command_template).safe_substitute(variables)
    timeout = int(os.getenv("OCTOPUS_IMAGE_GEN_TIMEOUT_SECONDS") or "180")
    completed = subprocess.run(
        command,
        cwd=str(output_dir),
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"image generation command failed ({completed.returncode}): {stderr[:800]}"
        )
    if not output.is_file():
        raise RuntimeError(
            "image generation command completed but did not create the expected output"
        )

    files = {view: output for view in AGENT_VISUAL_VIEWS}
    return AgentVisualResult(provider=provider, prompt=prompt, files=files)


def _generate_mock_visuals(
    *,
    provider: str,
    prompt: str,
    agent_id: str,
    display_name: str,
    output_dir: Path,
) -> AgentVisualResult:
    files: dict[str, Path] = {}
    for view in AGENT_VISUAL_VIEWS:
        out = output_dir / f"{view}.svg"
        out.write_text(
            _mock_visual_svg(agent_id=agent_id, display_name=display_name, view=view),
            encoding="utf-8",
        )
        files[view] = out
    return AgentVisualResult(provider=provider, prompt=prompt, files=files)


def _mock_visual_svg(*, agent_id: str, display_name: str, view: str) -> str:
    width = {"front": 210, "side": 118, "back": 220}.get(view, 210)
    opacity = "0.72" if view == "back" else "1"
    seed = sum(ord(c) for c in agent_id) % 360
    hue_a = (seed + 42) % 360
    hue_b = (seed + 290) % 360
    safe_name = _escape_xml(display_name[:30] or agent_id)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="820" viewBox="0 0 640 820">
  <defs>
    <linearGradient id="body" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="hsl({hue_a}, 92%, 70%)"/>
      <stop offset="0.58" stop-color="hsl({hue_b}, 82%, 58%)"/>
      <stop offset="1" stop-color="#171b23"/>
    </linearGradient>
    <radialGradient id="core" cx="50%" cy="28%" r="58%">
      <stop offset="0" stop-color="#ffe28a"/>
      <stop offset="0.46" stop-color="#ff9f6e"/>
      <stop offset="1" stop-color="#df3cf0"/>
    </radialGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="9" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <ellipse cx="320" cy="704" rx="248" ry="52" fill="#facc15" opacity=".10" stroke="#facc15" stroke-width="2"/>
  <ellipse cx="320" cy="710" rx="158" ry="32" fill="#000000" opacity=".20" stroke="#ffffff" stroke-width="1"/>
  <g opacity="{opacity}" filter="url(#glow)">
    <rect x="{320 - width / 2:.1f}" y="220" width="{width}" height="330" rx="{min(width / 2, 92):.1f}" fill="url(#body)" opacity=".22" stroke="#7dd3fc" stroke-width="2"/>
    <circle cx="320" cy="260" r="{58 if view != "side" else 45}" fill="url(#core)"/>
    <rect x="{320 - width * .34:.1f}" y="320" width="{width * .68:.1f}" height="202" rx="{width * .22:.1f}" fill="url(#body)" stroke="#facc15" stroke-width="2" opacity=".96"/>
    <path d="M{320 - width * .42:.1f} 396 C{320 - width * .75:.1f} 448 {320 - width * .72:.1f} 540 {320 - width * .36:.1f} 584" fill="none" stroke="#f472b6" stroke-width="34" stroke-linecap="round"/>
    <path d="M{320 + width * .42:.1f} 396 C{320 + width * .75:.1f} 448 {320 + width * .72:.1f} 540 {320 + width * .36:.1f} 584" fill="none" stroke="#f472b6" stroke-width="34" stroke-linecap="round"/>
    <path d="M{320 - width * .2:.1f} 514 C{320 - width * .42:.1f} 586 {320 - width * .3:.1f} 650 {320 - width * .05:.1f} 670" fill="none" stroke="#df3cf0" stroke-width="32" stroke-linecap="round"/>
    <path d="M{320 + width * .2:.1f} 514 C{320 + width * .42:.1f} 586 {320 + width * .3:.1f} 650 {320 + width * .05:.1f} 670" fill="none" stroke="#df3cf0" stroke-width="32" stroke-linecap="round"/>
    <circle cx="{320 - width * .42:.1f}" cy="246" r="14" fill="#37306b"/>
    <circle cx="{320 + width * .42:.1f}" cy="246" r="14" fill="#37306b"/>
  </g>
  <text x="320" y="764" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" font-weight="700" fill="#ffffff">{safe_name}</text>
</svg>"""


def _escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

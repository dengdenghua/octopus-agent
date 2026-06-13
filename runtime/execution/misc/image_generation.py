from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

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
        "Generate a reusable 2D game/HUD agent character information card, "
        "dark sci-fi interface mood, neon yellow accents, clean full body "
        "character silhouette, premium RPG character profile style, with "
        "compact readable stat-card panels inspired by the agent identity. "
        "Avoid 3D render, avoid wireframe, avoid rough sketch, avoid cropped body."
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
    if resolved_provider in {"agnes", "agnes-ai", "agnes-image"}:
        return _generate_with_agnes(
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


def _generate_with_agnes(
    *,
    provider: str,
    prompt: str,
    agent_id: str,
    display_name: str,
    output_dir: Path,
) -> AgentVisualResult:
    agnes_config = _resolve_agnes_config()
    api_key = agnes_config["api_key"]
    if not api_key:
        raise ValueError("AGNES_API_KEY not found")

    base_url = agnes_config["base_url"].rstrip("/")
    model = agnes_config["model"]
    size = os.getenv("AGNES_IMAGE_SIZE", "").strip() or "1024x1536"
    timeout = int(os.getenv("OCTOPUS_IMAGE_GEN_TIMEOUT_SECONDS") or "180")

    files: dict[str, Path] = {}
    for view in AGENT_VISUAL_VIEWS:
        view_prompt = _agent_visual_view_prompt(
            base_prompt=prompt,
            view=view,
            agent_id=agent_id,
            display_name=display_name,
        )
        data = _post_agnes_image_generation(
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=view_prompt,
            size=size,
            timeout=timeout,
        )
        out = output_dir / f"{view}.png"
        _write_agnes_image_result(data, out, timeout=timeout)
        files[view] = out

    return AgentVisualResult(provider=provider, prompt=prompt, files=files)


def _resolve_agnes_config() -> dict[str, str]:
    env_key = (os.getenv("AGNES_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    env_base_url = (
        os.getenv("AGNES_BASE_URL", "").strip() or "https://apihub.agnes-ai.com/v1"
    )
    env_model = os.getenv("AGNES_IMAGE_MODEL", "").strip()
    config = {
        "api_key": env_key,
        "base_url": env_base_url,
        "model": env_model or "agnes-image-2.1-flash",
    }
    if config["api_key"]:
        return config

    entry = _load_agnes_custom_model_entry()
    if not entry:
        return config

    api_key = str(entry.get("api_key") or "").strip()
    base_url = str(entry.get("base_url") or "").strip()
    model = _pick_agnes_image_model(entry) or config["model"]
    return {
        "api_key": api_key,
        "base_url": base_url or config["base_url"],
        "model": env_model or model,
    }


def _load_agnes_custom_model_entry() -> dict[str, Any] | None:
    try:
        from runtime.platform.process.paths import app_paths

        path = app_paths().custom_models_path
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    candidates = [
        entry
        for entry in data.values()
        if isinstance(entry, dict) and _is_agnes_custom_model_entry(entry)
    ]
    return candidates[0] if candidates else None


def _is_agnes_custom_model_entry(entry: dict[str, Any]) -> bool:
    base_url = str(entry.get("base_url") or "").lower()
    if "agnes-ai.com" in base_url:
        return True
    models = entry.get("models")
    if isinstance(models, list):
        return any(str(model).startswith("agnes-") for model in models)
    return str(entry.get("model") or "").startswith("agnes-")


def _pick_agnes_image_model(entry: dict[str, Any]) -> str | None:
    models = entry.get("models")
    if isinstance(models, list):
        for model in models:
            model_name = str(model or "").strip()
            if model_name.startswith("agnes-image-"):
                return model_name
    model = str(entry.get("model") or "").strip()
    return model if model.startswith("agnes-image-") else None


def _agent_visual_view_prompt(
    *,
    base_prompt: str,
    view: str,
    agent_id: str,
    display_name: str,
) -> str:
    view_label = {
        "front": "front view, facing the viewer",
        "side": "side profile view, facing screen right",
        "back": "back view, showing rear silhouette and equipment",
    }.get(view, view)
    return (
        f"{base_prompt} Generate ONLY the {view_label}. "
        f"Use a single full-body character centered on one vertical info card. "
        f"Include concise UI labels for name '{display_name}', id '{agent_id}', "
        f"view '{view.upper()}', role, core skills, and loadout. "
        "Keep the background transparent or very dark neutral so the web UI can "
        "composite it. Do not create multiple separate characters in this image."
    )


def _post_agnes_image_generation(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    timeout: int,
) -> dict[str, Any]:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "size": size,
            "n": 1,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/images/generations",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"agnes API error: HTTP {exc.code} - {body[:800]}") from exc
    except OSError as exc:
        raise RuntimeError(f"agnes API request failed: {type(exc).__name__}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"agnes API returned non-JSON: {raw[:200]!r}") from exc


def _write_agnes_image_result(data: dict[str, Any], output: Path, *, timeout: int) -> None:
    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise RuntimeError(f"agnes API returned no image data: {data!r}")
    first = items[0]
    if not isinstance(first, dict):
        raise RuntimeError(f"agnes API returned invalid image data: {first!r}")

    if isinstance(first.get("b64_json"), str) and first["b64_json"]:
        output.write_bytes(base64.b64decode(first["b64_json"]))
        return

    url = first.get("url")
    if not isinstance(url, str) or not url:
        raise RuntimeError(f"agnes API returned no image URL: {first!r}")
    req = urllib.request.Request(url, headers={"Accept": "image/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            output.write_bytes(resp.read())
    except OSError as exc:
        raise RuntimeError(
            f"agnes image download failed: {type(exc).__name__}: {exc}"
        ) from exc


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

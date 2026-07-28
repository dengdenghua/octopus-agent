---
name: agnes-image-generate
description: "使用 Agnes AI 网关从文字描述生成图像。agnes-image-2.1-flash 同时支持文生图和图生图。当用户需要生成图片、插画或封面时调用此技能。"
enabled: true
aliases: [agnes_image, generate_image_agnes]
---

# Agnes Image Generation

通过 Agnes AI Gateway (`https://apihub.agnes-ai.com/v1`) 调用图像生成模型，
返回托管在 `platform-outputs.agnes-ai.space` 上的 PNG URL。

## Models

| ID | 用途 |
|----|----|
| `agnes-image-2.1-flash` | text→image + image→image（默认，最新） |
| `agnes-image-2.0-flash` | image→image（旧版，可选） |

## Configuration

需要在环境变量或配置中设置 API Key：

```bash
export AGNES_API_KEY=sk-...
# 或回退使用通用 OpenAI 兼容变量
export OPENAI_API_KEY=sk-...
```

可选覆盖 base URL（默认 `https://apihub.agnes-ai.com/v1`）：
```bash
export AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
```

## Usage

### 文生图

```python
from agnes_image_generate import generate_image

result = generate_image(
    prompt="a tiny red panda holding a paintbrush, soft studio lighting, 4k",
)
# {"url": "https://platform-outputs.agnes-ai.space/.../image.png", "model": "agnes-image-2.1-flash"}
```

### 指定尺寸 + 数量

```python
result = generate_image(
    prompt="cinematic dragon over Hong Kong skyline at dusk",
    size="1152x768",
    n=2,
)
# {"urls": ["...", "..."], ...}
```

### 图生图（参考图）

```python
result = generate_image(
    prompt="same cat but in oil painting style",
    image="https://example.com/cat.png",
)
```

## Returns

```json
{
  "url": "https://platform-outputs.agnes-ai.space/images/text-to-image/.../xxx.png",
  "urls": ["..."],
  "model": "agnes-image-2.1-flash",
  "created": 1780826984,
  "usage": {"total_tokens": 0}
}
```

When `n > 1` the result includes both `url` (first one) and `urls` (full list)
for caller convenience.

## Errors

- `ValueError("AGNES_API_KEY not found")` — neither `AGNES_API_KEY` nor
  `OPENAI_API_KEY` is set.
- `RuntimeError("agnes API error: ...")` — non-200 response from the gateway;
  the underlying message is preserved.

---
name: agnes-video-generate
description: "使用 Agnes AI 网关异步提交视频生成任务（默认 wait=false，立即返回 task_id 不阻塞）。支持文字到视频、图像到视频、关键帧过渡。模型 agnes-video-v2.0，最多 441 帧（8n+1 规则）。提交后用 agnes-video-poll 查询进度。"
enabled: true
aliases: [agnes_video, generate_video_agnes]
---

# Agnes Video Generation

通过 Agnes AI Gateway (`https://apihub.agnes-ai.com/v1/videos`) **异步**提交视频生成任务。
默认立即返回 `task_id`，不阻塞当前 ReAct 轮次；后续用 `agnes-video-poll` 查询结果。

## Models

| ID | 用途 |
|----|----|
| `agnes-video-v2.0` | 文/图→视频，可包含同步音频 |

## Constraints

- `num_frames` 必须满足 **8n+1**（典型值：49, 81, 121, 161, ..., 441）
- `frame_rate` ∈ [1, 60]
- 任务异步执行，单次轮询超时 ~60s 不一定完成

## Configuration

```bash
export AGNES_API_KEY=sk-...
# 可选
export AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
```

## Usage

### 文生视频（默认非阻塞，立即返回 task_id）

```python
from agnes_video_generate import generate_video

result = generate_video(
    prompt="A cinematic shot of a red panda walking through a forest at golden hour",
    width=1152,
    height=768,
    num_frames=49,
    frame_rate=24,
    wait=False,        # 默认值；立即返回 task_id，不阻塞 ReAct 轮次
)
# {"task_id": "task_xyz", "status": "queued", "model": "agnes-video-v2.0"}
```

**为什么默认非阻塞**：视频渲染通常 30-180 秒，阻塞 LLM 轮次浪费上下文配额。
模型应该在收到 `task_id` 后继续与用户对话，等用户问"好了吗？"或几轮后再调
`agnes-video-poll` 查询结果。

### 等到完成后才返回（仅在调用脚本/批处理场景使用）

```python
result = generate_video(
    prompt="...",
    wait=True,            # 显式阻塞，直到 status=completed 或超时
    max_wait_seconds=300,
)
# {"task_id": "...", "status": "completed", "video_url": "https://..."}
```

### 后续轮询（推荐配合 agnes-video-poll 使用）

```python
# 在后续对话轮次中：
from agnes_video_generate import poll_video
status = poll_video("task_xyz")
# 或者用独立 skill：
status = agnes_video_poll(task_id="task_xyz")
```

### 图生视频

```python
result = generate_video(
    prompt="The woman slowly turns around and looks back at the camera",
    image="https://example.com/portrait.png",
    num_frames=121,
    frame_rate=24,
)
```

### 关键帧过渡

```python
result = generate_video(
    prompt="Smooth cinematic transition between the two keyframes",
    image=[
        "https://example.com/keyframe1.png",
        "https://example.com/keyframe2.png",
    ],
    num_frames=121,
)
```

## Returns

提交时（或 wait=False）：
```json
{"task_id": "task_xxx", "status": "queued", "model": "agnes-video-v2.0",
 "video_url": null, "size": "1152x768", "seconds": "2.0"}
```

完成时：
```json
{"task_id": "...", "status": "completed",
 "video_url": "https://...mp4", "progress": 100,
 "completed_at": 1780827120}
```

## Errors

- `ValueError("num_frames must satisfy 8n+1")` — 帧数不合法
- `RuntimeError("agnes video task failed: ...")` — 任务终态为 failed
- `TimeoutError("agnes video task did not complete within ...s")` — 等待超时

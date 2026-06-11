---
name: agnes-video-poll
description: "查询 Agnes AI 视频生成任务的状态。配合 agnes-video-generate（异步提交）使用——后者返回 task_id 后，模型可在后续轮次用 task_id 调用本技能查看进度或获取 video_url。"
enabled: true
aliases: [agnes_video_poll, poll_agnes_video, check_video_task]
---

# agnes-video-poll

查询某个 Agnes 视频生成任务的当前状态。

## 何时使用

`agnes-video-generate` 默认以 `wait: false` 模式提交任务，立即返回 `task_id`，
视频在后台渲染（约 30–180 秒）。在以下场景调用本技能轮询：
- 用户问"我的视频好了吗？"
- 几轮对话后想主动检查进度
- 需要 `video_url` 把视频展示/下载给用户

## 参数

- `task_id`（必填）：`agnes-video-generate` 返回的任务 id
- `api_key`（可选）：覆盖 `AGNES_API_KEY` 环境变量

## 返回

```python
{
  "task_id": "task_01234...",
  "status": "completed",   # queued / running / completed / failed
  "model": "agnes-video-v2.0",
  "progress": 100,         # 0..100
  "video_url": "https://..." # 仅 status=completed 时存在
}
```

如果 `status == "failed"`，会有 `error` 字段说明失败原因。

## 完整流程示例

```python
# 1) 提交（非阻塞，立即返回）
submit = agnes_video_generate(
    prompt="一只猫在弹钢琴",
    wait=False,  # 默认值
)
# {"task_id": "task_xyz", "status": "queued"}

# 2) 模型继续与用户对话；视频在后台渲染

# 3) 用户询问时轮询
status = agnes_video_poll(task_id="task_xyz")
# {"status": "completed", "video_url": "https://..."}
```

## 相关技能

- `agnes-video-generate`：提交新的视频生成任务
- `agnes-image-generate`：图像生成（文生图 / 图生图）

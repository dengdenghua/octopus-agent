# 剪辑工坊接口

基础路径：`/api/plugins/clip-studio/projects/{project_id}`。

## 读取

- `GET ?view=summary|tracks|clips|full`
- `full` 额外返回 `media[]` 与 `markers[]`。
- `tracks[]` 提供可见名称、类型、锁定/隐藏/静音/独奏状态和片段数量。
- `clips[]` 与 `textClips[]` 都带轨道 ID、轨道名称、起止秒数和持续时间。

## 原子编辑

`POST /edit`

```json
{
  "description": "为发布会样片加入标题",
  "validateOnly": false,
  "operations": [
    {"type": "add_text", "text": "全新发布", "atSec": 1, "durationSec": 2}
  ]
}
```

可用操作：

- 轨道：`add_track`、`set_track`、`remove_track`
- 媒体：`import_media`、`add_clip`
- 片段：`move_clip`、`trim_clip`、`split_clip`、`duplicate_clip`、`remove_clip`（可带 `ripple`）、`remove_range`、`close_gap`、`cut_silences`、`set_clip`、`set_speed`
- 文字：`add_text`、`set_text`、`remove_text_clip`、`import_srt`、`set_subtitle_style`
- 外观：`add_transition`、`remove_transition`、`add_effect`、`remove_effect`、`set_color_grading`
- 标记：`add_marker`、`remove_marker`

一次请求最多 50 个操作。任一操作失败时 `rolledBack=true`，此前操作不会落盘。

`cut_silences` 使用本地媒体真实音轨的 RMS/dB 分析，参数为 `clipId`、可选
`thresholdDb`（默认 -40）、`minSilenceSec`（默认 0.5）、`padSec`（默认 0.1）。
检测和波纹切除属于同一原子操作；无音轨或媒体不可读时失败并回滚。

## 历史与播放头

- `POST /history`：`{"action":"undo|redo","steps":1}`，最多 20 步。
- `POST /view`：`seek` 需要 `toSec`；`play` 可带 `fromSec`；`pause` 无额外字段。

## 视觉快照

`POST /snapshot` 从真实本地媒体渲染时间线帧：

```json
{"times": [1.2, 4.8], "maxDim": 640}
```

也可传 `fromSec`、`toSec`、`count` 均匀采样，最多 8 帧。返回的 `frames[].path`
是本地 PNG，必须实际查看图片后才能下视觉结论。当前渲染覆盖媒体裁切/速度、亮度、
对比度、饱和度、模糊、锐化、颗粒、色温/色调和字幕；尚未合成的效果或转场会出现在
`warnings[]`，不能忽略后宣称完全一致。

## 诊断

`GET /diagnostics` 返回：

- `clip_overlap`：同轨片段重叠，错误。
- `timeline_gap`：主视频轨道存在黑场，错误。
- `empty_track`：空轨道，警告。
- `tiny_clip`：短于两帧的疑似误剪片段，警告。
- `media_missing`：片段引用的媒体不存在，错误。
- `caption_out_of_video`：字幕超出视频画面范围，警告。

`clean=true` 只代表没有错误级问题，警告仍需结合创作意图判断。

---
type: "MemorySubsystem"
title: "Memory · Hemolymph (Context)"
description: "Context Composer · 给 planner 组装上下文（最近 trajectory + learned rules + memories）。"
tags: ["backend", "memory"]
tier: "core"
---
# Memory · Hemolymph (Context)

> Context Composer · 给 planner 组装上下文（最近 trajectory + learned rules + memories）。

**Source**: `runtime/memory/hemolymph/`

## Exports

- `ContextComposer`
- `ContextEngine`
- `TruncationContextEngine`
- `estimate_tokens`

## Modules

| Module | Summary |
| --- | --- |
| `code_index.py` | Auto-retrieve relevant *source* chunks for planner grounding. |
| `composer.py` | — |
| `embedding_backend.py` | Unified, configurable text embedder for octopus's code index. |
| `image_semantic_index.py` | Local image semantic search + face grouping over a persisted index. |
| `repo_context.py` | Auto-retrieve relevant codebase context from the project wiki. |
| `semantic_code_index.py` | Read-only semantic search over the work-mode KB's persisted code index. |
| `semantic_rank.py` | Generic semantic ranking — order candidate texts by relevance to a query. |
| `video_semantic_index.py` | Local video semantic search + face grouping + speech search over a persisted index. |
| `video_watchdog.py` | Auto incremental indexing for the local video library. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `code_index.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def reciprocal_rank_fusion(rankings, k)` | Fuse several ranked key-lists into one order by Reciprocal Rank Fusion. |
| func | `def retrieve_code_context(query, root, budget_tokens, max_chunks, ttl, _sink, strict_explicit_paths)` | Return the source chunks most relevant to ``query`` as a prompt section, or ``None`` when there is no source or no chunk overlaps the query. |

### `composer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_recent_compose_snapshots(limit)` | Return up to ``limit`` most-recent compose snapshots, newest last. |
| func | `def estimate_tokens(text)` |  |
| func | `def score_skill_relevance(query, name, affinity, description)` | Lexical relevance of a skill to the task. Zero infra: English word overlap + name/affinity substring hits + CJK bigram overlap. Higher = mor |
| class | `class ContextEngine(ABC)` | Abstract base for pluggable context-compression strategies. |
| class | `class TruncationContextEngine(ContextEngine)` | Default engine — drops whole segments from the lowest-priority buckets first until the total fits within the budget. |
| class | `class ContextComposer` |  |

### `embedding_backend.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def embed_model()` |  |
| func | `def embed_endpoint()` |  |
| func | `def backend_info()` | Describe the active embedding backend — for the setup UI / CLI to show the user, in plain terms, what their stack is wired to. |
| func | `def available()` | True when SOME embedding backend is reachable — a remote endpoint is set, or fastembed / sentence-transformers is importable. Cheap; doesn't |
| func | `def embed_texts(texts)` | Embed ``texts`` via the configured backend (remote endpoint preferred, else in-process). ``None`` when no backend is available; ``[]`` for n |
| func | `def get_encoder()` | Return an ``.encode``-compatible encoder for the configured backend, or ``None`` when nothing is available. |

### `image_semantic_index.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def ort_providers()` | ONNX Runtime execution providers for the CLIP towers & face model. |
| func | `def embed_quantization()` | Quantization mode for the CLIP ONNX models, or ``None`` to keep default. |
| func | `def face_capable()` | True when a face detector is loaded (face grouping is available). |
| func | `def build_index(root, db_path, include_faces, max_files)` | Scan ``root`` for images and (re)build the persisted index. Returns a summary dict. Face embedding is optional — skipped when the detector i |
| func | `def search_by_text(query, top_k, db_path)` | Top-k images semantically closest to a text description. ``None`` when the semantic layer is unavailable (no index / no text tower). |
| func | `def search_by_image(image_path, top_k, db_path)` | Top-k images visually closest to a given image file. ``None`` when the semantic layer is unavailable. |
| func | `def group_faces(db_path, threshold)` | Cluster face embeddings into person groups. Returns ``None`` when face capability is off or no faces are indexed. Each group lists image pat |
| func | `def search_face(image_path, top_k, db_path)` | Find indexed images that contain the same face(s) as a given image. ``None`` when face capability is off. |
| func | `def classify_image(image_path, labels, db_path, top_k)` | Zero-shot classify an image with the CLIP text tower. |
| func | `def ocr_image(image_path, db_path)` | OCR an image via ``rapidocr_onnxruntime`` and persist the text. |
| func | `def find_duplicates(db_path, hash_threshold)` | Group near-duplicate images by dHash Hamming distance. |
| func | `def find_blurry(db_path, threshold)` | List images whose Laplacian sharpness is below ``threshold``. |
| func | `def sensitive_scan(db_path, top_k)` | Zero-shot score all indexed images against NSFW semantic labels. |
| func | `def filter_meta(db_path, year, month, file_type, location, min_width, min_height, person, scene)` | Filter the image library by metadata (all conditions must match). |
| func | `def train_category(name, image_paths, db_path)` | Few-shot train a custom category from example images. |

### `repo_context.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def is_private_agent_context_path(path)` | Whether a repo/wiki path is agent-private prompt material. |
| func | `def retrieve_repo_context(query, wiki_dir, budget_tokens, max_pages, _sink)` | Retrieve the wiki pages most relevant to ``query`` (BM25) as a prompt section. Returns ``None`` when there is no wiki or no page overlaps. |
| func | `def build_codebase_context(goal, strict_explicit_scope)` | Combined codebase grounding for a goal: relevant wiki pages (summaries) + the actual source chunks. Returns ``(prompt_section, sources)`` wh |
| func | `def render_codebase_context(goal)` | ``build_codebase_context``'s prompt section only — the existing string contract for callers that don't need the structured source list. |
| func | `def collect_codebase_sources(goal)` | The docs/chunks that ``render_codebase_context(goal)`` would inject, as structured ``{"kind", "title", "path"}`` dicts — for a UI grounding  |

### `semantic_code_index.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def search_persisted(query, top_k, db_path)` | Top-k semantically-nearest chunks from the persisted KB index, or ``None`` when the semantic layer isn't available (no DB / no embedding bac |

### `semantic_rank.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def rank(query, candidates, top_k)` | Rank ``candidates`` by relevance to ``query``. |

### `video_semantic_index.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def tenant_video_db_path(scope)` | Return an index path isolated to one verified tenant/actor scope. |
| func | `def face_capable()` | True when a face detector is loaded (face grouping is available). |
| func | `def hardware_accel()` | Report the configured hardware-acceleration settings. |
| func | `def build_video_index(root, db_path, include_faces, include_transcript, max_files, max_frames_per_video, min_interval_sec, incremental)` | Scan ``root`` for videos and (re)build the persisted keyframe index. |
| func | `def search_video_by_text(query, db_path, top_k)` | Top-k keyframes semantically closest to a text description. |
| func | `def search_video_by_image(image_path, db_path, top_k)` | Top-k keyframes visually closest to a given image file. |
| func | `def search_face_in_videos(image_path, db_path, top_k)` | Find video keyframes containing the same face(s) as a given image. |
| func | `def group_video_faces(db_path, threshold)` | Cluster face embeddings into person groups across videos. |
| func | `def search_video_by_speech(query, db_path)` | Simple text match over the transcribed speech of indexed videos. |
| func | `def classify_video(video_path, labels, db_path, top_k)` | Zero-shot classify a video by averaging label scores over its keyframes. |
| func | `def extract_frame_jpeg(video_path, time_sec)` | Decode a single frame of a video and return it as JPEG bytes. |
| func | `def ocr_video_keyframes(query, root, db_path, top_k, min_interval_sec, max_frames)` | OCR the keyframes of every video under ``root`` and text-match ``query``. |

### `video_watchdog.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class VideoWatcher` | Background scanner that incrementally indexes a directory's videos. |
| func | `def start_watching(directory, interval_sec, include_faces, db_path, max_files)` | Start a watcher for ``directory`` (idempotent per directory). |
| func | `def stop_watching(directory, db_path)` | Stop and remove the watcher for ``directory``. Returns True if stopped. |
| func | `def stop_all()` |  |


## Who imports this

**15** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/core/`** · 2 file(s)
  - `runtime/core/cerebrum/_react_prompt_assembly_sections.py`
  - `runtime/core/cerebrum/llm_planner.py`
- **`runtime/execution/`** · 4 file(s)
  - `runtime/execution/suckers/code_intelligence_skills.py`
  - `runtime/execution/suckers/image_album_skills.py`
  - `runtime/execution/suckers/image_semantic_skills.py`
  - `runtime/execution/suckers/video_album_skills.py`
- **`runtime/memory/`** · 1 file(s)
  - `runtime/memory/learning/experience_ledger.py`
- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/config/builder.py`
- **`runtime/sensing/`** · 5 file(s)
  - `runtime/sensing/gateway/_observability_rollback_panels.py`
  - `runtime/sensing/gateway/local_brain.py`
  - `runtime/sensing/gateway/media_router.py`
  - `runtime/sensing/gateway/retrieve_router.py`
  - `runtime/sensing/gateway/wiki_router.py`
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`


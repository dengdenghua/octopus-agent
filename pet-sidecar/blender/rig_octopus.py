#!/usr/bin/env python3
"""
rig_octopus.py — 自动为章鱼 FBX 绑骨骼 + 触手摆动动画 + 导出 GLB

用法（命令行，无需打开 Blender GUI）：
    blender --background --python rig_octopus.py -- \
        --in "/absolute/path/to/章鱼.fbx" \
        --out "/absolute/path/to/octopus_rigged.glb"

可选参数：
    --tentacles 8     触手数量（默认 8）
    --bones 4         每条触手的骨骼节数（默认 4）
    --frames 120      动画总帧数（默认 120）
    --wobble 0.35     触手摆动幅度（弧度，默认 0.35）
    --loop 1          是否循环动画（默认 1）

原理：
  1. 导入 FBX，找到顶点最多的网格（章鱼主体）。
  2. 用 KMeans 把“远端(触手)顶点”按方向聚成 N 簇，得到每条触手的朝向。
  3. 每条触手从身体表面到触手尖端布一条骨链。
  4. 用 Blender 自动权重(Bone Heat)把网格绑到骨骼。
  5. 给每条触手的骨骼加正弦摆动关键帧。
  6. 导出带动画的 GLB。

依赖：Blender 4.x（自带 numpy）。运行后请检查控制台输出的诊断信息。
"""
import argparse
import math

import bpy
import numpy as np


# ─────────────────────────── 参数 ───────────────────────────
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", required=True)
    p.add_argument("--out", dest="out_path", required=True)
    p.add_argument("--tentacles", type=int, default=8)
    p.add_argument("--bones", type=int, default=4)
    p.add_argument("--frames", type=int, default=120)
    p.add_argument("--wobble", type=float, default=0.35)
    p.add_argument("--loop", type=int, default=1)
    return p.parse_args()


# ─────────────────────────── 清空场景 ───────────────────────────
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # 恢复到默认场景
    bpy.ops.wm.read_factory_settings(use_empty=False)


# ─────────────────────────── 导入 FBX ───────────────────────────
def import_fbx(path):
    bpy.ops.import_scene.fbx(filepath=path)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("未从 FBX 导入任何网格")
    # 取顶点最多的网格（章鱼主体）
    mesh_obj = max(meshes, key=lambda o: len(o.data.vertices))
    print(f"[rig] 主体网格: {mesh_obj.name} 顶点={len(mesh_obj.data.vertices)}")
    return mesh_obj


# ─────────────────────────── 几何分析 ───────────────────────────
def kmeans(points, k, iters=40, seed=0):
    """用 numpy 实现简单 KMeans，返回 (labels, centers)。"""
    rng = np.random.default_rng(seed)
    # 最远点采样初始化
    center_idx = [int(rng.integers(0, len(points)))]
    while len(center_idx) < k:
        d = np.min(
            np.linalg.norm(points[:, None, :] - points[np.array(center_idx)][None, :, :], axis=2),
            axis=1,
        )
        center_idx.append(int(np.argmax(d)))
    centers = points[np.array(center_idx)].copy()
    for _ in range(iters):
        d = np.linalg.norm(points[:, None, :] - centers[None, :, :], axis=2)
        labels = np.argmin(d, axis=1)
        new_centers = np.array(
            [points[labels == i].mean(axis=0) if np.any(labels == i) else centers[i] for i in range(k)]
        )
        if np.allclose(new_centers, centers):
            break
        centers = new_centers
    d = np.linalg.norm(points[:, None, :] - centers[None, :, :], axis=2)
    labels = np.argmin(d, axis=1)
    return labels, centers


def analyze_mesh(mesh_obj, n_tentacles):
    coords = np.array([v.co for v in mesh_obj.data.vertices])  # Nx3
    center = coords.mean(axis=0)
    d = np.linalg.norm(coords - center, axis=1)

    # 身体半径：取内层 60% 顶点的平均距离
    core = coords[d <= np.percentile(d, 60)]
    body_radius = float(np.mean(np.linalg.norm(core - center, axis=1)))

    # 远端顶点（触手）：距离 > 75% 最大距离
    outer = coords[d > 0.75 * d.max()]
    if len(outer) < n_tentacles * 16:
        raise RuntimeError("远端顶点太少，可能不是章鱼姿态，请检查网格")

    # KMeans 聚成触手簇
    labels, centers = kmeans(outer, n_tentacles)

    tentacles = []
    for i in range(n_tentacles):
        cl = outer[labels == i]
        if len(cl) == 0:
            continue
        tip = cl[np.argmax(np.linalg.norm(cl - center, axis=1))]
        direction = tip - center
        direction = direction / np.linalg.norm(direction)
        base = center + direction * body_radius
        tentacles.append(
            {
                "dir": direction,
                "base": base,
                "tip": tip,
                "len": float(np.linalg.norm(tip - base)),
            }
        )
    print(f"[rig] 检测到触手 {len(tentacles)} 条, body_radius={body_radius:.3f}")
    for i, t in enumerate(tentacles):
        print(f"  tentacle[{i}] dir=({t['dir'][0]:+.2f},{t['dir'][1]:+.2f},{t['dir'][2]:+.2f}) len={t['len']:.3f}")
    return center, body_radius, tentacles


# ─────────────────────────── 建骨骼 ───────────────────────────
def build_armature(center, tentacles, n_bones):
    arm_data = bpy.data.armatures.new("OctopusArm")
    arm_obj = bpy.data.objects.new("OctopusArm", arm_data)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones

    # 身体根骨
    root = eb.new("Root")
    root.head = (center[0], center[1], center[2])
    root.tail = (center[0], center[1] + 0.15, center[2])

    for i, t in enumerate(tentacles):
        prev = None
        for b in range(n_bones):
            t01_s = b / n_bones
            t01_e = (b + 1) / n_bones
            head = t["base"] + t["dir"] * (t["len"] * t01_s)
            tail = t["base"] + t["dir"] * (t["len"] * t01_e)
            bone = eb.new(f"Tentacle{i}_{b}")
            bone.head = (head[0], head[1], head[2])
            bone.tail = (tail[0], tail[1], tail[2])
            bone.parent = prev if prev else root
            prev = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj


# ─────────────────────────── 自动权重 ───────────────────────────
def bind_weights(mesh_obj, arm_obj):
    bpy.ops.object.select_all(action="DESELECT")
    mesh_obj.select_set(True)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    print("[rig] 自动权重绑定完成")


# ─────────────────────────── 触手动画 ───────────────────────────
def add_animation(arm_obj, n_tentacles, n_bones, frames, wobble, loop):
    scene = bpy.context.scene
    scene.frame_start = 0
    scene.frame_end = frames
    scene.render.fps = 30

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="POSE")
    pose = arm_obj.pose

    for i in range(n_tentacles):
        phase = i * (2 * math.pi / n_tentacles)
        for b in range(n_bones):
            # 越靠近尖端摆动越大
            t = (b + 1) / n_bones
            amp = wobble * t * t
            bone = pose.bones[f"Tentacle{i}_{b}"]
            for f in range(0, frames + 1, 2):
                time = f / 30.0
                bone.rotation_euler[0] = amp * math.sin(time * 3.0 + phase)
                bone.rotation_euler[1] = amp * 0.6 * math.sin(time * 2.4 + phase * 1.3)
                bone.rotation_euler[2] = amp * 0.4 * math.sin(time * 2.0 + phase * 0.7)
                bone.keyframe_insert(data_path="rotation_euler", frame=f)

    bpy.ops.object.mode_set(mode="OBJECT")

    # 可选循环
    if loop:
        scene.frame_end = frames
        scene.frame_start = 0
    print("[rig] 触手动画关键帧完成")


# ─────────────────────────── 导出 GLB ───────────────────────────
def export_glb(out_path):
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format="GLB",
        use_selection=False,
        export_animations=True,
        export_frame_range=(bpy.context.scene.frame_start, bpy.context.scene.frame_end),
        export_apply=True,
        export_anim_single_armature=True,
    )
    print(f"[rig] 已导出: {out_path}")


# ─────────────────────────── 主流程 ───────────────────────────
def main():
    args = parse_args()
    reset_scene()
    mesh_obj = import_fbx(args.in_path)
    center, body_radius, tentacles = analyze_mesh(mesh_obj, args.tentacles)
    arm_obj = build_armature(center, tentacles, args.bones)
    bind_weights(mesh_obj, arm_obj)
    add_animation(arm_obj, len(tentacles), args.bones, args.frames, args.wobble, args.loop)
    export_glb(args.out_path)
    print("[rig] 完成 ✅")


if __name__ == "__main__":
    main()
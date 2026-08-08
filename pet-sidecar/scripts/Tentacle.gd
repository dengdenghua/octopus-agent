extends Node3D

## High-quality tentacle: multi-segment IK chain with
## natural curl, tapered thickness, gradient color, and dual-row suckers

var base_angle_deg: float = 0.0
var segment_count: int = 8
var total_length: float = 1.2
var thickness: float = 0.13
var phase: float = 0.0
var speed: float = 0.7
var curl_amount: float = 0.5

var segment_meshes: Array = []
var sucker_nodes: Array = []
var outline_meshes: Array = []
var angles: Array = []
var seg_lens: Array = []
var _initialized: bool = false
var _seg_materials: Array = []
var _base_color: Color = Color(0.60, 0.35, 0.96)
var _tip_color: Color = Color(0.35, 0.15, 0.75)

func initialize(body_node: Node3D) -> void:
	_build_segments()

func _build_segments() -> void:
	for child in get_children():
		child.queue_free()
	segment_meshes.clear()
	sucker_nodes.clear()
	outline_meshes.clear()
	angles.clear()
	seg_lens.clear()
	_seg_materials.clear()
	var seg_len: float = total_length / float(max(1, segment_count))
	for i in range(segment_count):
		angles.append(0.0)
		seg_lens.append(seg_len)
		var t01: float = float(i) / float(max(1, segment_count - 1))
		var radius_scale: float = 1.0 - t01 * 0.75
		var seg_r: float = thickness * radius_scale
		var sm = MeshInstance3D.new()
		var cm = CapsuleMesh.new()
		cm.radius = seg_r
		cm.height = seg_len * 1.6
		cm.radial_segments = 8
		cm.rings = 4
		sm.mesh = cm
		var mat = StandardMaterial3D.new()
		var col: Color = _base_color.lerp(_tip_color, t01 * 0.7)
		mat.albedo_color = col
		mat.roughness = 0.5 + t01 * 0.2
		mat.metallic = 0.0
		mat.rim = 0.5 - t01 * 0.2
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_PER_PIXEL
		sm.material_override = mat
		_seg_materials.append(mat)
		add_child(sm)
		segment_meshes.append(sm)
		var outline = MeshInstance3D.new()
		var om = CapsuleMesh.new()
		om.radius = seg_r * 1.15
		om.height = seg_len * 1.7
		om.radial_segments = 8
		om.rings = 4
		outline.mesh = om
		var o_mat = StandardMaterial3D.new()
		o_mat.albedo_color = Color(0.15, 0.05, 0.3, 0.85)
		o_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		o_mat.cull_mode = BaseMaterial3D.CULL_FRONT
		outline.material_override = o_mat
		add_child(outline)
		outline_meshes.append(outline)
		var suckers = Node3D.new()
		sm.add_child(suckers)
		sucker_nodes.append(suckers)
		var sucker_r: float = seg_r * 0.28
		var num_suckers: int = 2 if i > 1 else 1
		for j in range(num_suckers):
			for side in [-1, 1]:
				var su = MeshInstance3D.new()
				var sum = SphereMesh.new()
				sum.radius = sucker_r
				sum.height = sucker_r * 1.5
				sum.radial_segments = 6
				sum.rings = 4
				su.mesh = sum
				var sucker_ang: float = float(side) * (0.4 + float(j) * 0.4)
				su.position = Vector3(sin(sucker_ang) * seg_r * 0.65, -seg_len * 0.2 + float(j) * seg_len * 0.4, -cos(sucker_ang) * seg_r * 0.65)
				var su_mat = StandardMaterial3D.new()
				var su_col: Color = Color(0.9, 0.7, 1.0, 0.9).lerp(Color(0.4, 0.2, 0.7), t01 * 0.5)
				su_mat.albedo_color = su_col
				su_mat.roughness = 0.6
				su_mat.rim = 0.3
				su.material_override = su_mat
				suckers.add_child(su)
	_initialized = true

func apply_materials(body_mat: Material) -> void:
	pass

func _ready() -> void:
	if not _initialized:
		_build_segments()

func update(delta: float, time: float, mouse_pos: Vector3, mouse_influence: float, body_global: Vector3, bounce_y: float) -> void:
	if angles.size() != segment_count or seg_lens.size() != segment_count:
		_build_segments()
		return
	var base_rad: float = deg_to_rad(base_angle_deg)
	var wave: float = sin(time * speed + phase) * 0.25
	var wave2: float = cos(time * speed * 0.7 + phase * 1.3) * 0.15
	var target_dir: Vector2 = Vector2(cos(base_rad), sin(base_rad))
	var to_mouse: Vector2 = Vector2(mouse_pos.x - body_global.x, mouse_pos.z - body_global.z)
	if to_mouse.length() > 0.01:
		var mouse_attract: float = mouse_influence * exp(-to_mouse.length() * 0.8)
		target_dir = target_dir.lerp(to_mouse.normalized(), mouse_attract).normalized()
	var start_pt: Vector3 = body_global + Vector3(cos(base_rad) * 0.38, bounce_y - 0.2, sin(base_rad) * 0.38)
	var points: Array = [start_pt]
	var current: Vector3 = start_pt
	for i in range(segment_count):
		var a: float = angles[i]
		var t01: float = float(i) / float(segment_count)
		var curl: float = curl_amount * t01 * t01 * 0.8
		var seg_a: float = base_rad + wave * (0.4 + t01 * 0.3) - curl + a
		var slen: float = seg_lens[i]
		var dy: float = sin(seg_a * 0.5) * 0.08 + wave2 * t01 * 0.5 - t01 * 0.15
		var step: Vector3 = Vector3(cos(seg_a) * slen, dy, sin(seg_a) * slen)
		current = current + step
		points.append(current)
	var last_idx: int = points.size() - 1
	if last_idx > 0:
		var tip = points[last_idx] as Vector3
		var target_tip: Vector3 = start_pt + Vector3(target_dir.x * total_length * 0.7, -0.35 + wave2 * 0.2, target_dir.y * total_length * 0.7)
		var ik_correction: Vector3 = (target_tip - tip) * 0.25
		var ai: int = angles.size() - 1
		if ai >= 0:
			angles[ai] = clamp(float(angles[ai]) + ik_correction.x * 0.4, -1.0, 1.0)
	current = start_pt
	var prev: Vector3 = start_pt
	for i in range(segment_count):
		if i + 1 >= points.size():
			break
		var a: float = angles[i]
		var t01: float = float(i) / float(segment_count)
		var curl: float = curl_amount * t01 * t01 * 0.8
		var seg_a: float = base_rad + wave * (0.4 + t01 * 0.3) - curl + a
		var slen: float = seg_lens[i]
		var dy: float = sin(seg_a * 0.5) * 0.08 + wave2 * t01 * 0.5 - t01 * 0.15
		var step: Vector3 = Vector3(cos(seg_a) * slen, dy, sin(seg_a) * slen)
		current = current + step
		points[i + 1] = current
		if i < segment_meshes.size():
			var sm = segment_meshes[i] as MeshInstance3D
			var om = outline_meshes[i] as MeshInstance3D if i < outline_meshes.size() else null
			if sm:
				var seg_center: Vector3 = (prev + current) * 0.5
				sm.global_position = seg_center
				if om: om.global_position = seg_center
				var seg_dir: Vector3 = (current - prev)
				if seg_dir.length() > 0.001:
					seg_dir = seg_dir.normalized()
					var up: Vector3 = Vector3.UP
					if abs(seg_dir.dot(up)) > 0.95:
						up = Vector3.RIGHT
					var basis = Basis.looking_at(seg_dir, up)
					sm.global_basis = basis
					sm.rotate_object_local(Vector3(1, 0, 0), PI * 0.5)
					if om:
						om.global_basis = basis
						om.rotate_object_local(Vector3(1, 0, 0), PI * 0.5)
				var bounce_scale: float = 1.0 + bounce_y * 0.2 * (1.0 - t01)
				var radius_scale: float = (1.0 - t01 * 0.75) * bounce_scale
				sm.scale = Vector3(radius_scale, 1.0 / max(0.01, slen) * (thickness * 1.5), radius_scale)
				if om:
					om.scale = Vector3(radius_scale * 1.15, 1.0 / max(0.01, slen) * (thickness * 1.5) * 1.15, radius_scale * 1.15)
		prev = current
	for i in range(angles.size()):
		angles[i] = float(angles[i]) * 0.9

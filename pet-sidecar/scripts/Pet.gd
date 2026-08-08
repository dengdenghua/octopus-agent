extends Node3D

## High-quality stylized octopus pet
## Pixar-inspired design: pear-shaped body, large expressive eyes,
## curly gradient tentacles, toon shading with rim light and outline

signal clicked

const TENTACLE_COUNT = 8
const BODY_RADIUS = 0.55
const BODY_HEIGHT = 0.75

@onready var body_mesh: MeshInstance3D = $Body
@onready var body_belly: MeshInstance3D = $BodyBelly
@onready var body_outline: MeshInstance3D = $BodyOutline
@onready var left_eye: Node3D = $LeftEye
@onready var right_eye: Node3D = $RightEye
@onready var mouth_node: MeshInstance3D = $Mouth
@onready var blush_l: MeshInstance3D = $BlushL
@onready var blush_r: MeshInstance3D = $BlushR

var tentacles_root: Node3D = null
var tentacles: Array = []
var time: float = 0.0
var mouse_pos_3d: Vector3 = Vector3.ZERO
var mouse_inside: bool = false
var is_being_dragged: bool = false
var drag_offset: Vector3 = Vector3.ZERO
var spring_velocity: Vector3 = Vector3.ZERO
var breath_scale: float = 1.0
var current_mood: String = "idle"
var blink_timer: float = 3.0
var is_blinking: bool = false
var blink_progress: float = 0.0
var eye_squint: float = 0.0
var bounce_offset: float = 0.0
var bounce_velocity: float = 0.0
var target_position: Vector3 = Vector3.ZERO
var move_speed: float = 0.0
var left_pupil: MeshInstance3D = null
var right_pupil: MeshInstance3D = null
var left_highlight1: MeshInstance3D = null
var left_highlight2: MeshInstance3D = null
var right_highlight1: MeshInstance3D = null
var right_highlight2: MeshInstance3D = null

func _ready() -> void:
	_build_eyes()
	_build_mouth()
	_build_blush()
	_build_tentacles()
	_setup_materials()
	_setup_outline()
	add_to_group("pet")

func _build_eyes() -> void:
	var eye_radius = BODY_RADIUS * 0.32
	var eye_spacing = BODY_RADIUS * 0.38
	var eye_y = BODY_RADIUS * 0.12
	var eye_z = BODY_RADIUS * 0.78
	for eye_side in [0, 1]:
		var eye_node = left_eye if eye_side == 0 else right_eye
		var side_sign: float = -1.0 if eye_side == 0 else 1.0
		eye_node.position = Vector3(side_sign * eye_spacing, eye_y, eye_z)
		var eye_white = MeshInstance3D.new()
		eye_white.name = "White"
		var esm = SphereMesh.new()
		esm.radius = eye_radius
		esm.height = eye_radius * 2.0
		esm.radial_segments = 24
		esm.rings = 16
		eye_white.mesh = esm
		eye_white.scale = Vector3(1.0, 1.15, 0.9)
		eye_node.add_child(eye_white)
		var iris = MeshInstance3D.new()
		iris.name = "Iris"
		var irm = SphereMesh.new()
		irm.radius = eye_radius * 0.68
		irm.height = irm.radius * 2.0
		irm.radial_segments = 20
		irm.rings = 12
		iris.mesh = irm
		iris.position = Vector3(0, 0, eye_radius * 0.55)
		eye_node.add_child(iris)
		var pupil = MeshInstance3D.new()
		pupil.name = "Pupil"
		var pm = SphereMesh.new()
		pm.radius = eye_radius * 0.42
		pm.height = pm.radius * 2.0
		pm.radial_segments = 16
		pm.rings = 10
		pupil.mesh = pm
		pupil.position = Vector3(0, 0, eye_radius * 0.85)
		eye_node.add_child(pupil)
		if eye_side == 0:
			left_pupil = pupil
		else:
			right_pupil = pupil
		var hl1 = MeshInstance3D.new()
		hl1.name = "Highlight1"
		var h1m = SphereMesh.new()
		h1m.radius = eye_radius * 0.22
		h1m.height = h1m.radius * 2.0
		h1m.radial_segments = 10
		h1m.rings = 6
		hl1.mesh = h1m
		hl1.position = Vector3(eye_radius * 0.2, eye_radius * 0.25, eye_radius * 1.05)
		eye_node.add_child(hl1)
		var hl2 = MeshInstance3D.new()
		hl2.name = "Highlight2"
		var h2m = SphereMesh.new()
		h2m.radius = eye_radius * 0.1
		h2m.height = h2m.radius * 2.0
		h2m.radial_segments = 8
		h2m.rings = 6
		hl2.mesh = h2m
		hl2.position = Vector3(-eye_radius * 0.15, -eye_radius * 0.1, eye_radius * 1.0)
		eye_node.add_child(hl2)
		if eye_side == 0:
			left_highlight1 = hl1
			left_highlight2 = hl2
		else:
			right_highlight1 = hl1
			right_highlight2 = hl2

func _build_mouth() -> void:
	var mouth_r = BODY_RADIUS * 0.08
	var mm = CapsuleMesh.new()
	mm.radius = mouth_r
	mm.height = mouth_r * 0.8
	mm.radial_segments = 8
	mm.rings = 6
	mouth_node.mesh = mm
	mouth_node.rotation_degrees = Vector3(0, 0, 90)
	mouth_node.position = Vector3(0, -BODY_RADIUS * 0.18, BODY_RADIUS * 0.72)
	mouth_node.scale = Vector3(1.5, 0.6, 1.0)

func _build_blush() -> void:
	var blush_r = BODY_RADIUS * 0.13
	for blush_node in [blush_l, blush_r]:
		var bm = SphereMesh.new()
		bm.radius = blush_r
		bm.height = blush_r * 0.6
		bm.radial_segments = 12
		bm.rings = 8
		blush_node.mesh = bm
		blush_node.rotation_degrees = Vector3(90, 0, 0)
	blush_l.position = Vector3(-BODY_RADIUS * 0.32, -BODY_RADIUS * 0.05, BODY_RADIUS * 0.68)
	blush_r.position = Vector3(BODY_RADIUS * 0.32, -BODY_RADIUS * 0.05, BODY_RADIUS * 0.68)

func _build_tentacles() -> void:
	tentacles_root = Node3D.new()
	tentacles_root.name = "Tentacles"
	add_child(tentacles_root)
	tentacles.clear()
	var angles = [10, 35, 58, 80, 100, 122, 145, 170]
	for i in range(TENTACLE_COUNT):
		var angle_deg: float = float(angles[i])
		var t_scene = load("res://scripts/Tentacle.gd").new()
		t_scene.base_angle_deg = angle_deg
		t_scene.segment_count = 8
		var len_factor: float = 1.0 + 0.25 * sin(float(i) * 0.7)
		t_scene.total_length = 1.1 * len_factor
		t_scene.thickness = BODY_RADIUS * 0.22 * (1.0 - 0.25 * abs(float(i) - 3.5) / 4.0)
		t_scene.phase = float(i) * 0.65
		t_scene.speed = 0.7 + float(i) * 0.06
		t_scene.curl_amount = 0.4 + 0.3 * sin(float(i) * 1.1)
		t_scene.initialize(self)
		tentacles_root.add_child(t_scene)
		tentacles.append(t_scene)

func _setup_materials() -> void:
	var body_mat = _make_body_material(Color(0.60, 0.35, 0.96), Color(0.45, 0.2, 0.85))
	body_mesh.material_override = body_mat
	body_mesh.scale = Vector3(1.0, 1.15, 0.95)
	var belly_mat = _make_belly_material()
	body_belly.material_override = belly_mat
	body_belly.scale = Vector3(0.65, 0.5, 0.7)
	body_belly.position = Vector3(0, -BODY_RADIUS * 0.3, BODY_RADIUS * 0.55)
	for eye_side in [0, 1]:
		var eye_node = left_eye if eye_side == 0 else right_eye
		var white_mat = StandardMaterial3D.new()
		white_mat.albedo_color = Color(1.0, 0.99, 0.97)
		white_mat.roughness = 0.15
		white_mat.metallic = 0.0
		white_mat.rim = 0.3
		(eye_node.get_node("White") as MeshInstance3D).material_override = white_mat
		var iris_color: Color = Color(0.25, 0.5, 0.95) if eye_side == 0 else Color(0.25, 0.5, 0.95)
		var iris_mat = StandardMaterial3D.new()
		iris_mat.albedo_color = iris_color
		iris_mat.roughness = 0.2
		iris_mat.metallic = 0.0
		(eye_node.get_node("Iris") as MeshInstance3D).material_override = iris_mat
		var pupil_mat = StandardMaterial3D.new()
		pupil_mat.albedo_color = Color(0.06, 0.04, 0.15)
		pupil_mat.roughness = 0.1
		pupil_mat.metallic = 0.0
		(eye_node.get_node("Pupil") as MeshInstance3D).material_override = pupil_mat
		var hl_mat = StandardMaterial3D.new()
		hl_mat.albedo_color = Color(1.0, 1.0, 1.0, 1.0)
		hl_mat.roughness = 0.05
		hl_mat.metallic = 0.0
		hl_mat.emission_enabled = true
		hl_mat.emission = Color(0.8, 0.8, 0.8)
		hl_mat.emission_energy_multiplier = 0.3
		(eye_node.get_node("Highlight1") as MeshInstance3D).material_override = hl_mat
		(eye_node.get_node("Highlight2") as MeshInstance3D).material_override = hl_mat
	var mouth_mat = StandardMaterial3D.new()
	mouth_mat.albedo_color = Color(0.35, 0.12, 0.55)
	mouth_mat.roughness = 0.7
	mouth_node.material_override = mouth_mat
	var blush_mat = StandardMaterial3D.new()
	blush_mat.albedo_color = Color(1.0, 0.55, 0.75, 0.6)
	blush_mat.roughness = 0.9
	blush_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	blush_mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	blush_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	blush_l.material_override = blush_mat
	blush_r.material_override = blush_mat
	for t in tentacles:
		if t.has_method("apply_materials"):
			t.apply_materials(body_mat)

func _setup_outline() -> void:
	var outline_mat = StandardMaterial3D.new()
	outline_mat.albedo_color = Color(0.15, 0.05, 0.3, 0.9)
	outline_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	outline_mat.cull_mode = BaseMaterial3D.CULL_FRONT
	var sm = SphereMesh.new()
	sm.radius = BODY_RADIUS * 1.08
	sm.height = sm.radius * 2.0 * 1.15
	sm.radial_segments = 24
	sm.rings = 16
	body_outline.mesh = sm
	body_outline.scale = Vector3(1.0, 1.15, 0.95)
	body_outline.material_override = outline_mat
	body_outline.position = Vector3(0, 0, -0.01)

func _make_body_material(base: Color, shadow: Color) -> StandardMaterial3D:
	var mat = StandardMaterial3D.new()
	mat.albedo_color = base
	mat.roughness = 0.45
	mat.metallic = 0.0
	mat.rim = 0.9
	mat.emission_enabled = true
	mat.emission = shadow
	mat.emission_energy_multiplier = 0.35
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_PER_PIXEL
	return mat

func _make_belly_material() -> StandardMaterial3D:
	var mat = StandardMaterial3D.new()
	mat.albedo_color = Color(0.92, 0.75, 1.0, 0.85)
	mat.roughness = 0.6
	mat.metallic = 0.0
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	mat.rim = 0.5
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_PER_PIXEL
	return mat

func set_mood(mood: String) -> void:
	current_mood = mood
	match mood:
		"idle": eye_squint = 0.0; move_speed = 0.5
		"thinking": eye_squint = 0.2; move_speed = 0.2
		"happy": eye_squint = 0.55; move_speed = 1.3
		"working": eye_squint = 0.0; move_speed = 0.9
		"error": eye_squint = 0.35; move_speed = 1.0
		"success": eye_squint = 0.7; move_speed = 1.8
		_: eye_squint = 0.0; move_speed = 0.5

func on_mouse_enter() -> void: mouse_inside = true
func on_mouse_exit() -> void: mouse_inside = false
func on_mouse_move(world_pos: Vector3) -> void: mouse_pos_3d = world_pos

func on_clicked() -> void:
	is_being_dragged = true
	drag_offset = global_position - mouse_pos_3d
	drag_offset.y = 0
	emit_signal("clicked")

func set_target_position(pos: Vector3, speed: float = 2.0) -> void:
	target_position = pos
	move_speed = speed

func _process(delta: float) -> void:
	time += delta
	_breath(delta)
	_blink(delta)
	_eyes(delta)
	_tentacles(delta)
	_move(delta)
	_bounce(delta)
	var s: float = breath_scale
	body_mesh.scale = Vector3(s, s * 1.15, s * 0.95)
	body_outline.scale = Vector3(s * 1.08, s * 1.15 * 1.08, s * 0.95 * 1.08)

func _breath(delta: float) -> void:
	var sp: float = 2.2
	var amp: float = 0.025
	match current_mood:
		"happy": sp = 3.8; amp = 0.04
		"working": sp = 3.0; amp = 0.03
		"thinking": sp = 1.2; amp = 0.012
	breath_scale = 1.0 + sin(time * sp) * amp

func _blink(delta: float) -> void:
	blink_timer -= delta
	if is_blinking:
		blink_progress += delta * 7.0
		if blink_progress >= 1.0:
			is_blinking = false
			blink_progress = 0.0
			var interval: float = 3.0 + randf() * 4.0
			match current_mood:
				"happy": interval = 1.2 + randf() * 1.5
				"working": interval = 2.0 + randf() * 2.0
			blink_timer = interval
	elif blink_timer <= 0:
		is_blinking = true
		blink_progress = 0.0

func _eyes(delta: float) -> void:
	var look = Vector3.ZERO
	if mouse_inside:
		var to_mouse = mouse_pos_3d - global_position
		if to_mouse.length() > 0.01:
			var flat = Vector3(to_mouse.x, to_mouse.y, to_mouse.z).normalized()
			look = Vector3(clamp(flat.x, -0.5, 0.5), clamp(flat.y * 0.4, -0.3, 0.3), clamp(flat.z * 0.3, 0.0, 0.5))
	var max_off: float = BODY_RADIUS * 0.1
	for pupil in [left_pupil, right_pupil]:
		if pupil:
			var target = Vector3(look.x * max_off, look.y * max_off, look.z * max_off + BODY_RADIUS * 0.22)
			pupil.position = pupil.position.lerp(target, 1.0 - exp(-8.0 * delta))
	var eye_sy: float = 1.0 - eye_squint * 0.65
	if is_blinking:
		eye_sy *= abs(1.0 - blink_progress * 2.0)
	for en in [left_eye, right_eye]:
		var w = en.get_node_or_null("White") as MeshInstance3D
		if w: w.scale.y = 1.15 * eye_sy
		var iris_n = en.get_node_or_null("Iris") as MeshInstance3D
		if iris_n: iris_n.scale.y = eye_sy
		var pu = en.get_node_or_null("Pupil") as MeshInstance3D
		if pu: pu.scale.y = eye_sy

func _tentacles(delta: float) -> void:
	var mi: float = 0.4 if mouse_inside else 0.0
	for t in tentacles:
		if t.has_method("update"):
			t.update(delta, time, mouse_pos_3d, mi, global_position, bounce_offset)

func _move(delta: float) -> void:
	if is_being_dragged:
		var new_pos = mouse_pos_3d + drag_offset
		new_pos.y = bounce_offset
		global_position = new_pos
		spring_velocity = Vector3.ZERO
		return
	var to_t = target_position - global_position
	to_t.y = 0
	var d = to_t.length()
	if d > 0.02:
		var dir = to_t.normalized()
		spring_velocity += dir * move_speed * delta * 8.0
		spring_velocity *= 0.92
		global_position += spring_velocity
	else:
		spring_velocity *= 0.9
	var facing: float = 0.0
	if spring_velocity.length() > 0.1:
		facing = atan2(-spring_velocity.x, 2.0) * 0.4
	rotation.y = lerp(rotation.y, facing, 1.0 - exp(-4.0 * delta))
	global_position.y = bounce_offset
	global_position.x = clamp(global_position.x, -8.0, 8.0)

func _bounce(delta: float) -> void:
	var speed_mag = spring_velocity.length()
	if speed_mag > 0.3:
		bounce_velocity -= speed_mag * delta * 2.5
	else:
		bounce_velocity -= 9.8 * delta
	bounce_velocity += bounce_offset * -25.0 * delta
	bounce_velocity *= 0.88
	bounce_offset += bounce_velocity * delta
	if bounce_offset > 0 and bounce_velocity > 0:
		bounce_velocity *= -0.35
	bounce_offset = min(bounce_offset, 0.25)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if not event.pressed and is_being_dragged:
			is_being_dragged = false

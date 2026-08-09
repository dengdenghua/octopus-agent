extends Node3D

## Desktop octopus pet backed by the real 章鱼.fbx model (Godot FBX import).
## Loads the rigged octopus mesh, plays its baked clip, and keeps the
## sidecar-facing API (set_mood / on_mouse_*) so Main can drive it.

const MODEL_PATH = "res://models/octopus/octopus.fbx"

var model_root: Node3D = null
var anim_player: AnimationPlayer = null
var time: float = 0.0
var current_mood: String = "idle"
var mouse_inside: bool = false
var mouse_pos_3d: Vector3 = Vector3.ZERO
var is_being_dragged: bool = false
var drag_offset: Vector3 = Vector3.ZERO
var spring_velocity: Vector3 = Vector3.ZERO
var target_position: Vector3 = Vector3.ZERO
var move_speed: float = 0.5
var bounce_offset: float = 0.0
var bounce_velocity: float = 0.0
## 程序化微动的相位与拖速(模型无骨骼,对整体做呼吸/轻摇)
var _breath_phase: float = 0.0
var _drag_speed: float = 0.0
var _last_drag_pos: Vector3 = Vector3.ZERO

func _ready() -> void:
	var scn: PackedScene = load(MODEL_PATH)
	if scn:
		model_root = scn.instantiate()
		model_root.name = "Model"
		add_child(model_root)
		_find_anim_player()
		_play_first_animation()
	_add_pickup_collision()
	add_to_group("pet")

## 给章鱼一个粗略的球体碰撞体,供 Main 的鼠标射线命中,从而支持点击/拖动。
func _add_pickup_collision() -> void:
	var body := StaticBody3D.new()
	body.name = "PickupBody"
	var shape := CollisionShape3D.new()
	var sphere := SphereShape3D.new()
	sphere.radius = 0.7
	shape.shape = sphere
	shape.position = Vector3(0, 0.3, 0)
	body.add_child(shape)
	add_child(body)

func _find_anim_player() -> void:
	anim_player = _find_recursive(self)

func _find_recursive(node: Node) -> AnimationPlayer:
	for child in node.get_children():
		if child is AnimationPlayer:
			return child
		var r: AnimationPlayer = _find_recursive(child)
		if r:
			return r
	return null

func _play_first_animation() -> void:
	if anim_player == null:
		return
	var names: Array = anim_player.get_animation_list()
	if names.size() > 0:
		anim_player.play(names[0])

func _set_anim_speed(s: float) -> void:
	if anim_player and anim_player.is_playing():
		anim_player.speed_scale = s

# ---- 对外接口(与 Pet.gd 一致,Main/Navigator 调用) ----
func set_mood(mood: String) -> void:
	current_mood = mood
	match mood:
		"thinking": move_speed = 0.2; _set_anim_speed(0.6)
		"happy": move_speed = 1.3; _set_anim_speed(1.4)
		"working": move_speed = 0.9; _set_anim_speed(1.2)
		"error": move_speed = 1.0; _set_anim_speed(1.1)
		"success": move_speed = 1.8; _set_anim_speed(1.6)
		"curious": move_speed = 0.7; _set_anim_speed(1.1)
		"tired": move_speed = 0.15; _set_anim_speed(0.4)
		_: move_speed = 0.5; _set_anim_speed(1.0)

func on_mouse_enter() -> void: mouse_inside = true
func on_mouse_exit() -> void: mouse_inside = false
func on_mouse_move(world_pos: Vector3) -> void: mouse_pos_3d = world_pos

func on_clicked() -> void:
	is_being_dragged = true
	drag_offset = global_position - mouse_pos_3d
	drag_offset.y = 0

func set_target_position(pos: Vector3, speed: float = 2.0) -> void:
	target_position = pos
	move_speed = speed

func _process(delta: float) -> void:
	time += delta
	_move(delta)
	_bounce(delta)
	_apply_life_motion(delta)

func _move(delta: float) -> void:
	if is_being_dragged:
		var new_pos: Vector3 = mouse_pos_3d + drag_offset
		new_pos.y = bounce_offset
		if delta > 0.0:
			var inst: float = (_last_drag_pos - new_pos).length() / delta
			_drag_speed = _drag_speed * 0.8 + inst * 0.2
		_last_drag_pos = new_pos
		global_position = new_pos
		spring_velocity = Vector3.ZERO
		target_position = new_pos
		return
	var to_t: Vector3 = target_position - global_position
	to_t.y = 0
	var d: float = to_t.length()
	if d > 0.02:
		var dir: Vector3 = to_t.normalized()
		spring_velocity += dir * move_speed * delta * 8.0
		spring_velocity *= 0.92
		global_position += spring_velocity
	else:
		spring_velocity *= 0.9
	if spring_velocity.length() > 0.1:
		rotation.y = lerp(rotation.y, atan2(-spring_velocity.x, spring_velocity.z), 1.0 - exp(-4.0 * delta))
	global_position.y = bounce_offset
	global_position.x = clamp(global_position.x, -8.0, 8.0)

func _bounce(delta: float) -> void:
	var speed_mag: float = spring_velocity.length()
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

## 程序化"生命感"微动(Godot hatch-pet 语义):
## - 待机:idle 原地呼吸鼓胀 + 缓慢漂浮轻摇 + 轻微点头,不移动位置
## - 拖动:摆动加快加大,并随拖速向前倾,模拟被拖着走
func _apply_life_motion(delta: float) -> void:
	if model_root == null:
		return
	_breath_phase += delta
	var dragging: bool = is_being_dragged
	# 呼吸:待机舒缓、拖动急促
	var breath_freq: float = 2.0 if dragging else 1.0
	var breath_amp: float = 0.035 if dragging else 0.02
	var b: float = sin(_breath_phase * breath_freq * TAU) * breath_amp
	model_root.scale = Vector3(1.0 - b * 0.6, 1.0 + b, 1.0 - b * 0.6)
	# 轻摇:待机缓慢漂浮、拖动快速摆动
	var sway_amp: float = 0.10 if dragging else 0.04
	var sway_freq: float = 6.0 if dragging else 0.85
	model_root.rotation.z = sin(_breath_phase * sway_freq) * sway_amp
	# 前后:待机轻微点头、拖动随拖速前倾
	var target_x: float
	if dragging:
		target_x = clamp(_drag_speed * 0.6, -0.3, 0.3)
	else:
		target_x = sin(_breath_phase * 1.3) * 0.025
	model_root.rotation.x = lerp(model_root.rotation.x, target_x, 1.0 - exp(-8.0 * delta))
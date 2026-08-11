extends Node3D

## Desktop octopus pet, unified to 2D Sprite.
##
## Renders the SAME atlas as the web in-page pet
## (frontend/public/images/octopus-pet.png, copied to res://sprites/octopus-pet.png)
## as a billboarded Sprite3D, sliced to the single 192x208 frame of the current
## mood (same row/frame layout as web `sprite-pet.tsx`). Keeps the 3D
## ground-walking / drag / bounce machinery so Main + Navigator keep working
## unchanged.

const SPRITE_PATH := "res://sprites/octopus-pet.png"

## 与网页端 sprite-pet.tsx 同一张 1920x1920 情绪网格精灵图(9 行 mood × 8 帧)。
const FRAME_W := 192
const FRAME_H := 208
const FRAME_COUNT := 8

## mood → 网格行号(与网页端 MOODS 表一致)。
const MOOD_ROW := {
	"idle": 0,
	"thinking": 1,
	"working": 2,
	"waiting": 3,
	"success": 4,
	"error": 5,
	"curious": 6,
	"tired": 7,
	"concerned": 8,
}

## 每帧停留秒数(与网页端 frameDuration 一致);循环类 mood 持续播放,
## 一次性 mood 播完停在末帧。
const MOOD_FRAME_SEC := {
	"idle": 0.18,
	"thinking": 0.24,
	"working": 0.13,
	"waiting": 0.22,
	"success": 0.10,
	"error": 0.18,
	"curious": 0.16,
	"tired": 0.28,
	"concerned": 0.18,
}
const LOOP_MOODS := {
	"idle": true, "thinking": true, "working": true, "waiting": true, "tired": true,
}

var sprite: Sprite3D = null
var time: float = 0.0
var current_mood: String = "idle"
var _frame_index: int = 0
var _frame_elapsed: float = 0.0
var mouse_inside: bool = false
var mouse_pos_3d: Vector3 = Vector3.ZERO
var is_being_dragged: bool = false
var drag_offset: Vector3 = Vector3.ZERO
var spring_velocity: Vector3 = Vector3.ZERO
var target_position: Vector3 = Vector3.ZERO
var move_speed: float = 0.5
var bounce_offset: float = 0.0
var bounce_velocity: float = 0.0
## 程序化微动的相位与拖速(对精灵整体做呼吸/轻摇)
var _breath_phase: float = 0.0
var _drag_speed: float = 0.0
var _last_drag_pos: Vector3 = Vector3.ZERO

func _ready() -> void:
	_build_sprite()
	_add_pickup_collision()
	add_to_group("pet")

## 用与网页端同一张 octopus-pet.png 精灵图搭建 billboard Sprite3D,
## 用 region 切出当前 mood 的单帧,避免整张情绪网格蒙太奇。
func _build_sprite() -> void:
	var tex: Texture2D = load(SPRITE_PATH)
	if tex == null:
		push_warning("[OctopusPet] missing sprite: " + SPRITE_PATH)
		return
	sprite = Sprite3D.new()
	sprite.name = "OctopusSprite"
	sprite.texture = tex
	# region 只显示单帧 192x208:pixel_size 决定世界尺寸,配合 Main 里节点
	# scale 0.35 得到约 1.3 世界单位高的显示尺寸;向上偏移半高让章鱼"站在"地平面。
	sprite.region_enabled = true
	_update_region()
	sprite.pixel_size = 0.018
	sprite.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	sprite.centered = true
	sprite.position.y = 0.55
	add_child(sprite)

## 按当前 mood 行 + 当前帧列刷新 region 切片。
func _update_region() -> void:
	if sprite == null:
		return
	var row: int = MOOD_ROW.get(current_mood, 0)
	sprite.region_rect = Rect2(
		_frame_index * FRAME_W, row * FRAME_H, FRAME_W, FRAME_H
	)

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

# ---- 对外接口(与 Pet.gd 一致,Main/Navigator 调用) ----
func set_mood(mood: String) -> void:
	current_mood = mood
	_frame_index = 0
	_frame_elapsed = 0.0
	_update_region()
	match mood:
		"thinking": move_speed = 0.2
		"happy": move_speed = 1.3
		"working": move_speed = 0.9
		"error": move_speed = 1.0
		"success": move_speed = 1.8
		"curious": move_speed = 0.7
		"tired": move_speed = 0.15
		_: move_speed = 0.5

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
	_animate_frames(delta)
	_apply_life_motion(delta)

## 帧动画:循环类 mood 持续循环,一次性 mood 播完停在末帧(对齐网页端)。
func _animate_frames(delta: float) -> void:
	if sprite == null:
		return
	var dur: float = MOOD_FRAME_SEC.get(current_mood, 0.2)
	_frame_elapsed += delta
	if _frame_elapsed < dur:
		return
	_frame_elapsed = 0.0
	if LOOP_MOODS.get(current_mood, false):
		_frame_index = (_frame_index + 1) % FRAME_COUNT
	elif _frame_index < FRAME_COUNT - 1:
		_frame_index += 1
	_update_region()

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

## 程序化"生命感"微动:
## - 待机:idle 原地呼吸鼓胀,不移动位置
## - 拖动:摆动加快加大,模拟被拖着走
## (billboard Sprite3D 忽略自身 rotation,故只做缩放呼吸)
func _apply_life_motion(delta: float) -> void:
	if sprite == null:
		return
	_breath_phase += delta
	var dragging: bool = is_being_dragged
	# 呼吸:待机舒缓、拖动急促
	var breath_freq: float = 2.0 if dragging else 1.0
	var breath_amp: float = 0.035 if dragging else 0.02
	var b: float = sin(_breath_phase * breath_freq * TAU) * breath_amp
	sprite.scale = Vector3(1.0 - b * 0.6, 1.0 + b, 1.0 - b * 0.6)

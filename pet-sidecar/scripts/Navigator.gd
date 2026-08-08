extends Node

## 2.5D Navigator - ground walking + obstacle avoidance on XZ plane

var move_speed: float = 2.5
var target: Vector3 = Vector3.ZERO
var has_target: bool = false
var arrive_threshold: float = 0.3
var obstacle_avoid_radius: float = 0.8
var _wander_target: Vector3 = Vector3.ZERO
var _wander_timer: float = 0.0

func _ready() -> void:
	target = Vector3.ZERO
	_wander_target = Vector3(randf_range(-5, 5), -1.0, randf_range(-0.3, 0.3))

func set_target(world_pos: Vector3) -> void:
	target = world_pos
	target.y = -1.0
	has_target = true

func clear_target() -> void:
	has_target = false

func update(delta: float) -> Vector3:
	var pet = get_node_or_null("/root/Main/Pet")
	if pet == null:
		return Vector3.ZERO
	var p = pet as Node3D
	if p == null:
		return Vector3.ZERO
	if not has_target:
		_wander_timer -= delta
		if _wander_timer <= 0:
			_wander_target = Vector3(randf_range(-6, 6), -1.0, randf_range(-0.3, 0.3))
			_wander_timer = 3.0 + randf() * 4.0
		target = _wander_target
	var to_target: Vector3 = target - p.global_position
	to_target.y = 0
	var dist: float = to_target.length()
	if dist < arrive_threshold:
		if has_target:
			has_target = false
		return Vector3.ZERO
	var dir: Vector3 = to_target / dist
	var avoidance: Vector3 = _compute_avoidance(p.global_position)
	dir = (dir + avoidance * 0.5).normalized()
	var velocity: Vector3 = dir * move_speed
	if abs(velocity.x) > 0.05:
		p.rotation.y = lerp(p.rotation.y, atan2(-velocity.x, velocity.z) * 0.5, 1.0 - exp(-5.0 * delta))
	if pet.has_method("set_target_position"):
		p.call("set_target_position", p.global_position + velocity * delta, move_speed)
	return velocity

func _compute_avoidance(pos: Vector3) -> Vector3:
	var avoid: Vector3 = Vector3.ZERO
	var margin: float = 0.8
	if pos.x < -7.0 + margin:
		avoid.x += 1.0
	if pos.x > 7.0 - margin:
		avoid.x -= 1.0
	# 窗口矩形避障:宠物靠近窗口时沿最短法推向两侧推开。
	var dw = get_node_or_null("/root/Main/DesktopWorld")
	if dw != null:
		var rects: Array = []
		if dw.get("window_rects_world") != null:
			rects = dw.get("window_rects_world")
		for r in rects:
			var push: Vector3 = _push_out_of_rect(pos, r)
			avoid += push
	return avoid

func _push_out_of_rect(pos: Vector3, r: Dictionary) -> Vector3:
	var x0: float = float(r.get("x0", 0.0))
	var x1: float = float(r.get("x1", 0.0))
	var z0: float = float(r.get("z0", 0.0))
	var z1: float = float(r.get("z1", 0.0))
	var pad: float = 0.5
	if pos.x < x0 - pad or pos.x > x1 + pad or pos.z < z0 - pad or pos.z > z1 + pad:
		return Vector3.ZERO
	# 计算到矩形边缘的最短推离方向。
	var dx_left: float = pos.x - (x0 - pad)
	var dx_right: float = (x1 + pad) - pos.x
	var dz_near: float = pos.z - (z0 - pad)
	var dz_far: float = (z1 + pad) - pos.z
	var m: float = min(min(dx_left, dx_right), min(dz_near, dz_far))
	if m < 0.0:
		m = 0.0
	var strength: float = clamp(1.0 - m / (pad * 2.0), 0.0, 1.0)
	var eps: float = 0.001
	if abs(m - dx_left) < eps:
		return Vector3(-1.0, 0, 0) * strength
	elif abs(m - dx_right) < eps:
		return Vector3(1.0, 0, 0) * strength
	elif abs(m - dz_near) < eps:
		return Vector3(0, 0, -1.0) * strength
	else:
		return Vector3(0, 0, 1.0) * strength

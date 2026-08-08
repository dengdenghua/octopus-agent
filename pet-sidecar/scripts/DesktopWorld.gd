extends Node

## Desktop World Model
## Detects screen bounds, taskbar/Dock, and builds walkable zones

var screen_rect: Rect2 = Rect2(0, 0, 1440, 900)
var taskbar_rect: Rect2 = Rect2()
var ground_y_screen: float = 860.0
var dock_height: float = 0.0
var walkable_zones: Array = []
var perches: Array = []
var window_platforms: Array = []
var world_scale: float = 0.01

# 由 Electron 上报的窗口矩形(世界坐标),Navigator 用它们做避障。
# 每项: { x0, x1, z0, z1 } —— XZ 平面上的轴对齐矩形。
var window_rects_world: Array = []

const GROUND_OFFSET = -1.5
const WORLD_HALF_WIDTH = 8.0

func _ready() -> void:
	_detect_screen()
	_detect_taskbar()
	_build_zones()
	_generate_perches()

func _detect_screen() -> void:
	var screen = DisplayServer.screen_get_size()
	screen_rect = Rect2(0, 0, screen.x, screen.y)

func _detect_taskbar() -> void:
	if OS.has_feature("macos"):
		dock_height = 80.0
		taskbar_rect = Rect2(0, screen_rect.size.y - 36, screen_rect.size.x, 36)
		ground_y_screen = screen_rect.size.y - dock_height - 20
	else:
		taskbar_rect = Rect2(0, screen_rect.size.y - 48, screen_rect.size.x, 48)
		ground_y_screen = screen_rect.size.y - 48 - 20

func _build_zones() -> void:
	world_scale = (WORLD_HALF_WIDTH * 2.0) / screen_rect.size.x
	walkable_zones.clear()
	walkable_zones.append({"type": "ground", "rect": Rect2(0, ground_y_screen - 30, screen_rect.size.x, 30)})

func _generate_perches() -> void:
	perches.clear()
	perches.append(_screen_to_world(Vector2(screen_rect.size.x * 0.15, ground_y_screen)))
	perches.append(_screen_to_world(Vector2(screen_rect.size.x * 0.5, ground_y_screen)))
	perches.append(_screen_to_world(Vector2(screen_rect.size.x * 0.85, ground_y_screen)))
	perches.append(_screen_to_world(Vector2(screen_rect.size.x * 0.3, ground_y_screen - 200)))
	perches.append(_screen_to_world(Vector2(screen_rect.size.x * 0.7, ground_y_screen - 150)))

func _screen_to_world(sp: Vector2) -> Vector3:
	var x: float = (sp.x - screen_rect.size.x * 0.5) * world_scale
	var z: float = (ground_y_screen - sp.y) * world_scale
	return Vector3(x, GROUND_OFFSET, z)

func world_to_screen(wp: Vector3) -> Vector2:
	var sx: float = wp.x / world_scale + screen_rect.size.x * 0.5
	var sy: float = ground_y_screen - (wp.z - GROUND_OFFSET) / world_scale
	return Vector2(sx, sy)

func get_nearest_perch(pos: Vector3) -> Vector3:
	if perches.is_empty():
		return Vector3.ZERO
	var best = perches[0] as Vector3
	var best_d: float = 1e9
	for p in perches:
		var pv = p as Vector3
		var d = pv.distance_squared_to(pos)
		if d < best_d:
			best_d = d
			best = pv
	return best

func get_random_wander_target(current: Vector3) -> Vector3:
	if perches.is_empty():
		return Vector3(randf_range(-WORLD_HALF_WIDTH * 0.8, WORLD_HALF_WIDTH * 0.8), GROUND_OFFSET, randf_range(-0.5, 0.5))
	var idx = randi() % perches.size()
	var p = perches[idx] as Vector3
	return Vector3(p.x + randf_range(-1.0, 1.0), GROUND_OFFSET, p.z + randf_range(-0.3, 0.3))

func register_window_platform(win_rect: Rect2) -> void:
	window_platforms.append(win_rect)

# 接收 Electron 上报的窗口矩形(屏幕坐标),转换为世界坐标避障矩形。
# 屏幕 y 向下为正、世界 z 向上为正,故纵轴取反。
func set_screen_windows(rects: Array) -> void:
	window_rects_world.clear()
	for r in rects:
		if not (r is Dictionary):
			continue
		var sx: float = float(r.get("x", 0))
		var sy: float = float(r.get("y", 0))
		var sw: float = float(r.get("w", 0))
		var sh: float = float(r.get("h", 0))
		if sw <= 0 or sh <= 0:
			continue
		var x0: float = (sx - screen_rect.size.x * 0.5) * world_scale
		var x1: float = (sx + sw - screen_rect.size.x * 0.5) * world_scale
		var z0: float = (ground_y_screen - (sy + sh)) * world_scale
		var z1: float = (ground_y_screen - sy) * world_scale
		window_rects_world.append({
			"x0": min(x0, x1), "x1": max(x0, x1),
			"z0": min(z0, z1), "z1": max(z0, z1),
		})

func update(delta: float) -> void:
	pass

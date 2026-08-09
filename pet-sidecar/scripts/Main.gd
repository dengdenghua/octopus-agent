extends Node3D

## Main entry for the octopus desktop pet sidecar
## Sets up transparent window, lights, camera, world, pet, brain, nav, IPC

const PET_SCENE = preload("res://scenes/OctopusPet.tscn")

var camera: Camera3D = null
var key_light: DirectionalLight3D = null
var fill_light: OmniLight3D = null
var world_env: WorldEnvironment = null
var desktop_world: Node = null
var pet: Node3D = null
var brain: Node = null
var navigator: Node = null
var ipc: Node = null
var pet_mouse_hover: bool = false
var last_mouse_screen: Vector2 = Vector2.ZERO

func _ready() -> void:
	_setup_window()
	_setup_camera()
	_setup_lighting()
	_setup_environment()
	_spawn_systems()
	_spawn_pet()
	_connect_signals()
	get_viewport().size_changed.connect(_on_viewport_resized)
	_on_viewport_resized()

func _setup_window() -> void:
	var screen = DisplayServer.screen_get_size()
	DisplayServer.window_set_position(Vector2i(0, 0))
	DisplayServer.window_set_size(screen)
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_TRANSPARENT, true)
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_ALWAYS_ON_TOP, true)
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_BORDERLESS, true)
	DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_MOUSE_PASSTHROUGH, true)

func _setup_camera() -> void:
	camera = Camera3D.new()
	camera.name = "Camera"
	camera.position = Vector3(0, 1.0, 3.2)
	camera.current = true
	camera.near = 0.1
	camera.far = 100.0
	camera.fov = 50.0
	add_child(camera)
	camera.look_at(Vector3(0, -0.3, 0), Vector3.UP)

func _setup_lighting() -> void:
	key_light = DirectionalLight3D.new()
	key_light.name = "KeyLight"
	key_light.rotation_degrees = Vector3(-55, 35, 0)
	key_light.light_color = Color(1.0, 0.96, 0.9)
	key_light.light_energy = 1.3
	key_light.shadow_enabled = false
	add_child(key_light)
	fill_light = OmniLight3D.new()
	fill_light.name = "FillLight"
	fill_light.position = Vector3(-2.5, 1.5, 2.5)
	fill_light.light_color = Color(0.75, 0.65, 1.0)
	fill_light.light_energy = 0.5
	fill_light.omni_range = 12.0
	add_child(fill_light)
	var rim = OmniLight3D.new()
	rim.name = "RimLight"
	rim.position = Vector3(0, 2.0, -2.5)
	rim.light_color = Color(0.9, 0.75, 1.0)
	rim.light_energy = 0.9
	rim.omni_range = 8.0
	add_child(rim)
	var bounce = OmniLight3D.new()
	bounce.name = "BounceLight"
	bounce.position = Vector3(0, -2.0, 1.5)
	bounce.light_color = Color(0.8, 0.7, 1.0)
	bounce.light_energy = 0.35
	bounce.omni_range = 6.0
	add_child(bounce)

func _setup_environment() -> void:
	world_env = WorldEnvironment.new()
	world_env.name = "WorldEnv"
	var env = Environment.new()
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.5, 0.4, 0.65)
	env.ambient_light_energy = 0.8
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.glow_enabled = true
	env.glow_intensity = 0.7
	env.glow_bloom = 0.5
	env.glow_hdr_threshold = 0.8
	env.glow_hdr_scale = 1.5
	env.ssao_enabled = false
	env.sdfgi_enabled = false
	env.volumetric_fog_enabled = false
	world_env.environment = env
	add_child(world_env)

func _spawn_systems() -> void:
	var dw_script = load("res://scripts/DesktopWorld.gd")
	desktop_world = dw_script.new()
	desktop_world.name = "DesktopWorld"
	add_child(desktop_world)
	var brain_script = load("res://scripts/PetBrain.gd")
	brain = brain_script.new()
	brain.name = "PetBrain"
	add_child(brain)
	var nav_script = load("res://scripts/Navigator.gd")
	navigator = nav_script.new()
	navigator.name = "Navigator"
	add_child(navigator)
	var ipc_script = load("res://scripts/IPCServer.gd")
	ipc = ipc_script.new()
	ipc.name = "IPC"
	add_child(ipc)
	if ipc.has_method("set_event_callback"):
		ipc.call("set_event_callback", Callable(self, "_on_ipc_event"))
	if brain.has_method("register_state_change_callback"):
		brain.call("register_state_change_callback", Callable(self, "_on_brain_state_changed"))

func _spawn_pet() -> void:
	pet = PET_SCENE.instantiate()
	pet.name = "Pet"
	pet.position = Vector3(0, -1.0, 0)
	pet.scale = Vector3(0.35, 0.35, 0.35)
	add_child(pet)

func _connect_signals() -> void:
	pass

func _on_viewport_resized() -> void:
	pass

func _on_ipc_event(event: String, data: Dictionary = {}) -> void:
	if brain and brain.has_method("on_agent_event"):
		brain.call("on_agent_event", event, data)

func _on_brain_state_changed(new_state: int) -> void:
	if pet and pet.has_method("set_mood"):
		if brain and brain.has_method("get_mood_for_state"):
			var mood = brain.call("get_mood_for_state")
			pet.call("set_mood", mood)

func _process(delta: float) -> void:
	_update_mouse_tracking()
	if brain:
		brain.call("update", delta, delta)
		if pet and pet.has_method("set_mood") and brain.has_method("get_mood_for_state"):
			pet.call("set_mood", brain.call("get_mood_for_state"))
	if desktop_world:
		desktop_world.call("update", delta)
	if navigator and brain:
		var st = brain.get("current_state") if brain.get("current_state") != null else 0
		var brain_state: int = int(st)
		if brain_state == 1:
			navigator.call("update", delta)
	if pet and camera:
		var target_cam_x: float = pet.global_position.x * 0.3
		camera.position.x = lerp(camera.position.x, target_cam_x, 1.0 - exp(-2.0 * delta))

func _update_mouse_tracking() -> void:
	var mouse_pos = DisplayServer.mouse_get_position()
	last_mouse_screen = mouse_pos
	if camera == null or pet == null:
		return
	var ray_origin: Vector3 = camera.project_ray_origin(mouse_pos)
	var ray_dir: Vector3 = camera.project_ray_normal(mouse_pos)
	var plane = Plane(Vector3.UP, -1.0)
	var intersect_result = plane.intersects_ray(ray_origin, ray_dir)
	if intersect_result != null:
		var intersect = intersect_result as Vector3
		if pet.has_method("on_mouse_move"):
			pet.call("on_mouse_move", intersect)
	var ray_end: Vector3 = ray_origin + ray_dir * 20.0
	var space_state = get_world_3d().direct_space_state
	if space_state == null:
		return
	var query = PhysicsRayQueryParameters3D.create(ray_origin, ray_end)
	query.collide_with_bodies = true
	query.collide_with_areas = false
	var result = space_state.intersect_ray(query)
	var over_pet: bool = not result.is_empty() and result.has("collider")
	if over_pet:
		var coll = result["collider"]
		var is_pet: bool = false
		var node = coll as Node
		while node != null:
			if node == pet:
				is_pet = true
				break
			node = node.get_parent()
		over_pet = is_pet
	if over_pet and not pet_mouse_hover:
		pet_mouse_hover = true
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_MOUSE_PASSTHROUGH, false)
		if pet.has_method("on_mouse_enter"):
			pet.call("on_mouse_enter")
	elif not over_pet and pet_mouse_hover:
		pet_mouse_hover = false
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_MOUSE_PASSTHROUGH, true)
		if pet.has_method("on_mouse_exit"):
			pet.call("on_mouse_exit")
	if over_pet and Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
		if pet.has_method("on_clicked"):
			pet.call("on_clicked")

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if pet and event.pressed and pet_mouse_hover and pet.has_method("on_clicked"):
			pet.call("on_clicked")

extends Node

## Pet Brain - FSM + Utility AI for behavior decisions

enum State {
	IDLE,
	ROAM,
	OBSERVE,
	SLEEP,
	CELEBRATE,
	ERROR_STATE,
	WAIT_USER
}

var current_state: int = State.IDLE
var state_time: float = 0.0
var agent_event: String = "idle"
var utility_scores: Dictionary = {}
var target_position: Vector3 = Vector3.ZERO

var _state_change_callbacks: Array = []

func _ready() -> void:
	utility_scores = {}
	for s in State.values():
		utility_scores[s] = 0.0
	current_state = State.IDLE

func register_state_change_callback(cb: Callable) -> void:
	_state_change_callbacks.append(cb)

func on_agent_event(event: String) -> void:
	agent_event = event
	match event:
		"success":
			_change_state(State.CELEBRATE)
		"error":
			_change_state(State.ERROR_STATE)
		"waiting_user":
			_change_state(State.WAIT_USER)

func update(delta: float, dt: float) -> State:
	state_time += delta
	_evaluate_utilities(delta)
	var highest: int = current_state
	var highest_score: float = -1.0
	for key in utility_scores:
		var score: float = utility_scores[key]
		if score > highest_score:
			highest_score = score
			highest = key
	if highest != current_state and highest_score > 0.5:
		var score_this: float = utility_scores[current_state] if utility_scores.has(current_state) else 0.0
		if highest_score > score_this + 0.2:
			_change_state(highest)
	_update_state_actions(delta)
	return current_state

func _evaluate_utilities(delta: float) -> void:
	utility_scores.clear()
	var is_waiting: bool = agent_event == "waiting_user"
	var is_success: bool = agent_event == "success"
	var is_error: bool = agent_event == "error"
	var is_working: bool = agent_event == "working"
	var is_thinking: bool = agent_event == "thinking"
	# 默认安静待着(IDLE 高分),仅在 working 时才允许漫游。
	utility_scores[State.IDLE] = 0.9
	var roam_base: float = 0.6 if is_working else 0.05
	utility_scores[State.ROAM] = roam_base + randf() * 0.1
	utility_scores[State.OBSERVE] = 0.9 if is_thinking else 0.2
	utility_scores[State.SLEEP] = 0.8 if state_time > 300 else 0.05
	utility_scores[State.CELEBRATE] = 1.0 if is_success else 0.0
	utility_scores[State.ERROR_STATE] = 1.0 if is_error else 0.0
	utility_scores[State.WAIT_USER] = 0.95 if is_waiting else 0.0

func _change_state(new_state: int) -> void:
	if current_state == new_state:
		return
	current_state = new_state
	state_time = 0.0
	for cb in _state_change_callbacks:
		if cb.is_valid():
			cb.call(new_state)

func _update_state_actions(delta: float) -> void:
	pass

func get_mood_for_state() -> String:
	match current_state:
		State.IDLE: return "idle"
		State.ROAM: return "working"
		State.OBSERVE: return "thinking"
		State.SLEEP: return "thinking"
		State.CELEBRATE: return "happy"
		State.ERROR_STATE: return "error"
		State.WAIT_USER: return "happy"
		_: return "idle"

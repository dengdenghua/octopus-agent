extends Node

## IPC Server - UDP listener for events from octopus-agent
## Receives agent state events and forwards to Pet Brain

const PORT = 8765
var peer: PacketPeerUDP = null
var is_listening: bool = false
var event_callback: Callable = Callable()

func _ready() -> void:
	_start_server()

func _start_server() -> void:
	peer = PacketPeerUDP.new()
	var err = peer.bind(PORT, "127.0.0.1")
	if err == OK:
		is_listening = true
		print("[IPC] Listening on UDP port ", PORT)
	else:
		is_listening = false
		push_warning("[IPC] Failed to bind UDP port " + str(PORT) + ": " + str(err))

func set_event_callback(cb: Callable) -> void:
	event_callback = cb

func _process(delta: float) -> void:
	if not is_listening or peer == null:
		return
	if peer.get_available_packet_count() > 0:
		var packet: PackedByteArray = peer.get_packet()
		var text: String = packet.get_string_from_utf8()
		_handle_message(text)

func _handle_message(msg: String) -> void:
	var event_type: String = ""
	if msg.begins_with("{"):
		var json = JSON.new()
		if json.parse(msg) == OK:
			var data = json.data
			if data and data is Dictionary:
				if data.has("type"):
					event_type = String(data["type"]).replace("agent.", "")
				# 世界更新消息:刷新桌面窗口矩形(用于避障)。
				if String(data.get("type", "")) == "world.windows" and data.has("windows"):
					_sync_windows(data["windows"])
	elif msg.begins_with("event:"):
		event_type = msg.substr(6).strip_edges().replace("agent.", "")
	if event_type != "":
		print("[IPC] Event: ", event_type)
		if event_callback.is_valid():
			event_callback.call(event_type)

func _sync_windows(windows) -> void:
	var dw = get_node_or_null("/root/Main/DesktopWorld")
	if dw == null or not dw.has_method("set_screen_windows"):
		return
	var rects: Array = []
	if windows is Array:
		for w in windows:
			if w is Dictionary:
				rects.append(w)
	dw.call("set_screen_windows", rects)
	print("[IPC] Windows synced: ", rects.size())

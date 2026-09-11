/** Guest settings contain no provider or invitation credentials. */
export function hotspotModelConfig(port: number): string {
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("本地隧道端口必须在 1 到 65535 之间");
  }
  return [
    'model_provider = "echo_hotspot"',
    "",
    "[model_providers.echo_hotspot]",
    'name = "Echo Hotspot"',
    `base_url = "http://127.0.0.1:${port}/v1"`,
    'env_key = "ECHO_HOTSPOT_TOKEN"',
    'wire_api = "responses"',
    "requires_openai_auth = false",
    "supports_websockets = false",
    "request_max_retries = 0",
    "stream_max_retries = 0",
    "",
  ].join("\n");
}

/** OpenCode uses the Responses SDK; the compatible SDK uses Chat Completions. */
export function hotspotOpenCodeConfig(port: number, model: string): string {
  hotspotModelConfig(port);
  if (!model.trim() || /[\r\n]/.test(model)) throw new Error("请填写热点支持的模型 ID");
  return JSON.stringify({
    $schema: "https://opencode.ai/config.json",
    model: `echo_hotspot/${model}`,
    provider: {
      echo_hotspot: {
        npm: "@ai-sdk/openai",
        name: "Echo AI 热点",
        options: {
          baseURL: `http://127.0.0.1:${port}/v1`,
          apiKey: "{env:ECHO_HOTSPOT_TOKEN}",
        },
        models: { [model]: { name: model, options: { store: false } } },
      },
    },
  }, null, 2);
}

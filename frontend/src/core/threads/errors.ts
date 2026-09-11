/** Translate known execution failures, including wrappers in saved history. */
export function publicExecutionErrorMessage(message: string): string {
  if (/model is unavailable|model_unavailable|model_not_found/i.test(message)) {
    return "所选模型当前不可用，请在输入框选择其他模型后重试。";
  }
  if (/free tier can only be used in opencode/i.test(message)) {
    return "当前 Zen 免费模型仅支持 OpenCode 引擎，请在输入框切换引擎后重试。";
  }
  if (message.includes("Responses tool catalog is too large")) {
    return "当前任务加载的工具过多，已超过执行接口上限。请减少启用的插件或工具后重试。";
  }
  return message;
}

function readErrorMessage(error: unknown): string | null {
  if (typeof error === "string" && error.trim()) {
    return error;
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  if (typeof error === "object" && error !== null) {
    const message = Reflect.get(error, "message");
    if (typeof message === "string" && message.trim()) {
      return message;
    }

    const nestedError = Reflect.get(error, "error");
    if (nestedError instanceof Error && nestedError.message.trim()) {
      return nestedError.message;
    }
    if (typeof nestedError === "string" && nestedError.trim()) {
      return nestedError;
    }
  }

  return null;
}

export function getStreamErrorMessage(
  error: unknown,
  streamEndpointUnavailableMessage: string,
): string {
  const message = readErrorMessage(error);
  if (!message) {
    return "Request failed.";
  }

  if (/^Stream failed:\s*(404|503)\b/i.test(message)) {
    return streamEndpointUnavailableMessage;
  }

  return publicExecutionErrorMessage(message);
}

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

  return message;
}

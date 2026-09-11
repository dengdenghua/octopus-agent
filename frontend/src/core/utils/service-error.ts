/** Describe a failed capability without turning missing data into success. */
export function serviceErrorMessage(error: unknown, chinese = true): string {
  const message = error instanceof Error ? error.message : String(error ?? "");
  if (/403|admin role|管理员|forbidden/i.test(message))
    return chinese
      ? "当前账号没有此功能的管理权限。请切换有权限的账号或联系管理员。"
      : "Your account cannot manage this feature. Use an authorized account or contact an administrator.";
  if (/401|unauthori[sz]ed|credentials.*expired/i.test(message))
    return chinese
      ? "登录或连接凭据已失效，请重新连接。"
      : "Your session or connection has expired. Please reconnect.";
  if (/404|not found/i.test(message))
    return chinese
      ? "当前服务未提供此功能或内容已下架。请刷新目录并检查服务版本。"
      : "This feature or item is unavailable. Refresh the catalog and check the service version.";
  if (/50[0234]|failed to fetch|network|timeout|超时/i.test(message))
    return chinese
      ? "服务暂时无法连接，数据尚未读取。请检查连接后重试。"
      : "The service is unavailable; data has not been loaded. Check the connection and retry.";
  return (
    message ||
    (chinese ? "暂时无法读取，请重试。" : "Unable to load. Please retry.")
  );
}

export function requireArray<T>(value: unknown, label: string): T[] {
  if (!Array.isArray(value))
    throw new Error(`${label}：服务返回的数据格式不完整，请重试。`);
  return value as T[];
}

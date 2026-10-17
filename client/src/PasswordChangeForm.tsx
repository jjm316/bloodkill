import { useRef, useState } from "react";

// 修改密码表单（工单 15）：验证旧密码后设置新密码与确认密码。当前登录保留，
// 其他设备由服务端撤销；密码只存在于本组件状态，成功/取消即随卸载丢弃。
export function PasswordChangeForm({ onSuccess, onCancel }: {
  onSuccess: () => void;
  onCancel: () => void;
}) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitting = useRef(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true); setError(null);
    try {
      const response = await fetch("/api/auth/password", {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
        body: JSON.stringify({ oldPassword, newPassword, confirmPassword: confirmation }),
      });
      const body = await response.json();
      if (!response.ok) { setError(body.message ?? "服务暂时不可用，请稍后重试。"); return; }
      onSuccess();
    } catch { setError("服务暂时不可用，请稍后重试。"); }
    finally { submitting.current = false; setBusy(false); }
  }

  return <form className="password-form" onSubmit={submit} noValidate>
    <label className="field" htmlFor="old-password">旧密码<input id="old-password" type="password" value={oldPassword} onChange={e => setOldPassword(e.target.value)} autoComplete="current-password" required /></label>
    <label className="field" htmlFor="new-password">新密码<input id="new-password" type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} autoComplete="new-password" required /></label>
    <label className="field" htmlFor="new-confirmation">确认新密码<input id="new-confirmation" type="password" value={confirmation} onChange={e => setConfirmation(e.target.value)} autoComplete="new-password" required /></label>
    <p className="hint">新密码为 6–12 个字符；修改后本机保持登录，其他设备需要用新密码重新登录。</p>
    {error && <div className="error" role="alert">{error}</div>}
    <div className="lobby-actions"><button type="submit" disabled={busy}>{busy ? "正在修改……" : "确认修改"}</button>
      <button type="button" disabled={busy} onClick={onCancel}>取消</button></div>
  </form>;
}

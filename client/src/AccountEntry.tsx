import { useRef, useState } from "react";

export interface Account { accountId: string; username: string; }

export function AccountEntry({ onAuthenticated }: { onAuthenticated: (account: Account) => void }) {
  const [registering, setRegistering] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/auth/${registering ? "register" : "login"}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
        body: JSON.stringify({ username, password, ...(registering ? { confirmPassword: confirmation } : {}) }),
      });
      const body = await response.json();
      if (!response.ok) { setError(body.message ?? "服务暂时不可用，请稍后重试。"); return; }
      setPassword(""); setConfirmation("");
      onAuthenticated(body.account);
    } catch { setError("服务暂时不可用，请稍后重试。"); }
    finally { submitting.current = false; setBusy(false); }
  }

  return <div className="lobby account-entry">
    <h1>鲜血盟约</h1>
    <h2>{registering ? "注册账号" : "登录"}</h2>
    <form onSubmit={submit}>
      <label className="field" htmlFor="account-username">用户名<input id="account-username" value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" required /></label>
      <p className="hint">2–16 个中文、英文字母、数字或下划线，英文字母不区分大小写。</p>
      <label className="field" htmlFor="account-password">密码<input id="account-password" type={visible ? "text" : "password"} value={password} onChange={e => setPassword(e.target.value)} autoComplete={registering ? "new-password" : "current-password"} required /></label>
      {registering && <label className="field" htmlFor="account-confirmation">确认密码<input id="account-confirmation" type={visible ? "text" : "password"} value={confirmation} onChange={e => setConfirmation(e.target.value)} autoComplete="new-password" required /></label>}
      <p className="hint">密码为 6–12 个字符，空格和大小写均按原输入保留。</p>
      <button type="button" aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? "隐藏密码" : "显示密码"}</button>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="lobby-actions"><button type="submit" disabled={busy}>{busy ? "正在提交……" : registering ? "注册并进入大厅" : "登录并进入大厅"}</button>
        <button type="button" disabled={busy} onClick={() => {
          setRegistering(!registering); setError(null);
          setPassword(""); setConfirmation(""); setVisible(false);
        }}>{registering ? "返回登录" : "注册账号"}</button></div>
    </form>
  </div>;
}

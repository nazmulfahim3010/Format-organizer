import { useState } from "react";
import { post, setToken } from "../api";

export default function Login({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const r = await post<{ token: string }>(`/api/auth/${mode}`, mode === "login" ? { email, password } : { email, password, name });
      setToken(r.token);
      onDone();
    } catch (x) { setErr((x as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <div className="mx-auto mt-24 max-w-sm">
      <h1 className="mb-1 text-2xl font-bold">SmartDoc</h1>
      <p className="mb-6 text-sm text-slate-500">Bring your own Word template. Paste your content. Get a correctly formatted DOCX.</p>
      <form onSubmit={submit} className="card space-y-3">
        {mode === "register" && (
          <div><label className="label">Name</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
        )}
        <div><label className="label">Email</label><input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div><label className="label">Password</label><input className="input" type="password" required minLength={mode === "register" ? 8 : 1} value={password} onChange={(e) => setPassword(e.target.value)} />
          {mode === "register" && <p className="mt-1 text-xs text-slate-400">At least 8 characters.</p>}</div>
        {err && <p className="text-sm text-red-600">{err}</p>}
        <button className="btn btn-primary w-full justify-center" disabled={busy}>{mode === "login" ? "Sign in" : "Create account"}</button>
        <button type="button" className="w-full text-center text-sm text-indigo-600" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "No account? Register" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}

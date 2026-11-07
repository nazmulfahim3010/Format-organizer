import { useEffect, useState } from "react";
import { getToken, setToken } from "./api";
import ArticleEditor from "./pages/ArticleEditor";
import Designs from "./pages/Designs";
import DocumentEditor from "./pages/DocumentEditor";
import Documents from "./pages/Documents";
import Login from "./pages/Login";
import TemplateEditor from "./pages/TemplateEditor";
import Templates from "./pages/Templates";

function useHash(): string {
  const [h, setH] = useState(location.hash || "#/documents");
  useEffect(() => {
    const f = () => setH(location.hash || "#/documents");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return h;
}

export default function App() {
  const [signedIn, setSignedIn] = useState(!!getToken());
  const hash = useHash();

  useEffect(() => {
    const f = () => setSignedIn(false);
    window.addEventListener("smartdoc:signed-out", f);
    return () => window.removeEventListener("smartdoc:signed-out", f);
  }, []);

  if (!signedIn) return <Login onDone={() => setSignedIn(true)} />;

  const parts = hash.replace(/^#\/?/, "").split("/");
  const id = Number(parts[1]);
  let page: React.ReactNode;
  if (parts[0] === "templates" && id) page = <TemplateEditor key={id} id={id} />;
  else if (parts[0] === "templates") page = <Templates />;
  else if (parts[0] === "documents" && id) page = <DocumentEditor key={id} id={id} />;
  else if (parts[0] === "designs") page = <Designs />;
  else if (parts[0] === "articles" && id) page = <ArticleEditor key={id} id={id} />;
  else page = <Documents />;

  const nav = (to: string, label: string) => (
    <a href={`#/${to}`} className={`rounded px-3 py-1 text-sm ${parts[0] === to ? "bg-indigo-600 text-white" : "text-slate-700 hover:bg-slate-200"}`}>{label}</a>
  );

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-10">
      <header className="flex items-center justify-between py-3">
        <div className="flex items-center gap-4">
          <span className="text-lg font-bold">SmartDoc</span>
          <nav className="flex gap-1">{nav("documents", "Documents")}{nav("templates", "Templates")}{nav("designs", "Designs")}</nav>
        </div>
        <button className="text-sm text-slate-500 hover:underline" onClick={() => { setToken(null); setSignedIn(false); }}>Sign out</button>
      </header>
      <main>{page}</main>
    </div>
  );
}

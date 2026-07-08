import { Sidebar } from "./Sidebar.js";

export function mountAppShell({ activeToolId, main, mainClassName = "workspace" }) {
  if (!main) {
    throw new Error("mountAppShell requires a main element.");
  }

  const sidebar = Sidebar({ activeId: activeToolId });
  main.className = mainClassName;
  document.body.insertBefore(sidebar.element, main);

  return { sidebar };
}

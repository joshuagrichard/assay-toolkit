import { TOOLS } from "../config/tools-nav.js";

function createBrand() {
  const brand = document.createElement("div");
  brand.className = "brand";
  brand.innerHTML = `
    <span class="brand-mark">AT</span>
    <span>Assay Toolkit</span>
  `;
  return brand;
}

function createToolLink(tool, activeId) {
  const link = document.createElement("a");
  link.className = `tool-button${tool.id === activeId ? " active" : ""}`;
  link.href = tool.href;
  link.textContent = tool.label;
  return link;
}

export function Sidebar({ activeId, tools = TOOLS }) {
  const aside = document.createElement("aside");
  aside.className = "sidebar";

  const label = document.createElement("div");
  label.className = "sidebar-label";
  label.textContent = "Tools";

  const nav = document.createElement("nav");
  nav.className = "tool-list";
  nav.setAttribute("aria-label", "Tool navigation");
  tools.forEach((tool) => nav.appendChild(createToolLink(tool, activeId)));

  aside.appendChild(createBrand());
  aside.appendChild(label);
  aside.appendChild(nav);

  return {
    element: aside,
    setActiveId(nextActiveId) {
      nav.querySelectorAll(".tool-button").forEach((button, index) => {
        button.classList.toggle("active", tools[index]?.id === nextActiveId);
      });
    },
  };
}

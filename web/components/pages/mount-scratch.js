import { mountAppShell } from "../layout/AppShell.js";

const main = document.getElementById("page-content");
if (!main) {
  throw new Error("Scratch assay page is missing #page-content.");
}

mountAppShell({
  activeToolId: "scratch_wound",
  main,
});

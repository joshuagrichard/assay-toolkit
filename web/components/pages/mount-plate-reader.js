import { mountAppShell } from "../layout/AppShell.js";

const main = document.getElementById("page-content");
if (!main) {
  throw new Error("Plate reader page is missing #page-content.");
}

mountAppShell({
  activeToolId: "plate_reader",
  main,
  mainClassName: "workspace plate-reader-workspace",
});

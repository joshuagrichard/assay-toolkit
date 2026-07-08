export const TOOLS = [
  {
    id: "scratch_wound",
    label: "Scratch Assay Analyzer",
    href: "/",
  },
  {
    id: "plate_reader",
    label: "Plate Reader Analyzer",
    href: "/plate-reader",
  },
];

export function toolById(id) {
  return TOOLS.find((tool) => tool.id === id);
}

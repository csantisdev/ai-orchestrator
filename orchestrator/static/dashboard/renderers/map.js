// Representación Mapa de los pasos de un contexto (spec §21.3, maqueta v5). Disposición
// determinista, sin simulación de fuerzas: x = orden del paso, y = carril del agente
// principal, commits en una franja inferior bajo el primer paso que los cita. `layoutMap` es
// puro (se prueba con node --test); `renderMap` arma el SVG y `select` atenúa lo no
// relacionado cambiando clases, sin regenerarlo.

import { svg } from "../core/dom.js";

export const LAYOUT = Object.freeze({
  laneLabel: 104, top: 28, column: 132, lane: 64, nodeWidth: 112, nodeHeight: 40,
  channelGap: 18, commitGap: 34, commitSize: 9, bottom: 24,
});

const AGENT_LABELS = { claude: "Claude", codex: "Codex", copilot: "Copilot", otros: "Otros", "sin agente": "Sin agente" };
const STATE_SYMBOL = { completed: "✓", in_progress: "●", pending: "○", skipped: "⤼", blocked: "■" };
const STATE_LABEL = { completed: "completado", in_progress: "en curso", pending: "pendiente", skipped: "omitido", blocked: "bloqueado" };

export function agentLabel(agent) {
  return AGENT_LABELS[agent] ?? agent;
}

// Columnas visibles: cada paso o, si su grupo está cerrado, el grupo entero (§21.4).
function columnsOf(dto, expanded) {
  const steps = dto.nodes.filter((node) => node.kind === "step");
  const groupOf = new Map();
  for (const group of dto.map.groups) {
    if (expanded.has(group.id)) continue;
    for (const member of group.members) groupOf.set(member, group);
  }
  const items = [];
  const columnOf = new Map();
  for (const step of steps) {
    const group = groupOf.get(step.id);
    if (group) {
      if (!items.length || items.at(-1).id !== group.id) items.push({ kind: "group", id: group.id, group });
    } else {
      items.push({ kind: "step", id: step.id, step });
    }
    columnOf.set(step.id, items.length - 1);
  }
  return { items, columnOf };
}

// Disposición completa para la ventana de columnas [start, start + max_columns).
export function layoutMap(dto, { expanded = new Set(), start = 0 } = {}) {
  const L = LAYOUT;
  const lanes = dto.map.lanes.length ? dto.map.lanes : ["sin agente"];
  const laneY = new Map(lanes.map((lane, index) => [lane, L.top + index * L.lane]));
  const { items, columnOf } = columnsOf(dto, expanded);
  const size = dto.map.max_columns;
  const first = Math.max(0, Math.min(start, Math.max(0, items.length - size)));
  const visible = items.slice(first, first + size);
  const x = (column) => L.laneLabel + (column - first) * L.column;
  const inWindow = (column) => column >= first && column < first + size;

  const nodes = visible.map((item, offset) => {
    const column = first + offset;
    if (item.kind === "group") {
      return {
        kind: "group", id: item.id, column, x: x(column), y: laneY.get(item.group.lane) ?? L.top,
        label: `Pasos ${item.group.from_idx}–${item.group.to_idx}`,
        sub: Object.entries(item.group.lanes).map(([lane, count]) => `${agentLabel(lane)} ${count}`).join(" · "),
        members: item.group.members,
      };
    }
    const step = item.step;
    const attrs = step.attrs;
    const ghosts = attrs.secondary.filter((agent) => laneY.has(agent)).map((agent) => ({ agent, y: laneY.get(agent) }));
    const badges = attrs.secondary.filter((agent) => !laneY.has(agent)).map((agent) => agentLabel(agent)[0]);
    return {
      kind: "step", id: step.id, column, x: x(column), y: laneY.get(attrs.lane) ?? L.top,
      idx: attrs.idx, state: step.state, symbol: STATE_SYMBOL[step.state] ?? "·",
      lane: attrs.lane, secondary: attrs.secondary, ghosts, badges,
      alignments: attrs.alignments, deviations: attrs.deviations, runs: attrs.runs, cost: attrs.cost_usd,
      singleCommits: dto.map.single_commits[step.id] ?? 0,
    };
  });

  const lanesBottom = L.top + lanes.length * L.lane;
  const channel = lanesBottom + L.channelGap;
  const commitTop = channel + L.channelGap;
  const shared = new Set(dto.map.shared);
  const stepColumn = new Map(dto.nodes.filter((node) => node.kind === "step").map((node) => [node.id, columnOf.get(node.id)]));
  const commits = [];
  let maxStack = 0;
  for (const node of dto.nodes) {
    if (node.kind !== "commit") continue;
    const place = dto.map.placement[node.id];
    if (!place) continue;
    const firstStep = dto.nodes.find((candidate) => candidate.kind === "step" && candidate.attrs.idx === place.column);
    const column = firstStep ? stepColumn.get(firstStep.id) : null;
    if (column === null || column === undefined || !inWindow(column)) continue;
    maxStack = Math.max(maxStack, place.stack);
    commits.push({
      id: node.id, label: node.label, shared: shared.has(node.id), column,
      x: x(column) + L.nodeWidth / 2, y: commitTop + place.stack * L.commitGap,
      hidden: dto.map.hidden_edges[node.id] ?? 0,
    });
  }
  const commitAt = new Map(commits.map((commit) => [commit.id, commit]));
  const nodeAt = new Map(nodes.map((node) => [node.id, node]));
  const holder = (stepId) => {
    const column = stepColumn.get(stepId);
    return inWindow(column) ? nodes[column - first] : null;
  };
  const edges = [];
  for (const edge of dto.edges) {
    if (edge.relation_type !== "cites") continue;
    const commit = commitAt.get(edge.target);
    const source = nodeAt.get(edge.source) ?? holder(edge.source);
    if (!commit || !source) continue;
    const sx = source.x + L.nodeWidth / 2 + (source.kind === "group" ? 0 : 0);
    const sy = source.y + L.nodeHeight;
    edges.push({
      source: source.id, step: edge.source, target: commit.id, shared: commit.shared,
      d: `M ${sx} ${sy} V ${channel} H ${commit.x} V ${commit.y - L.commitSize}`,
    });
  }
  const width = L.laneLabel + Math.max(visible.length, 1) * L.column + 16;
  const height = commits.length ? commitTop + maxStack * L.commitGap + L.commitSize + L.bottom : lanesBottom + L.bottom;
  return {
    width, height, lanes: lanes.map((lane) => ({ lane, label: agentLabel(lane), y: laneY.get(lane) })),
    columns: { first, size, total: items.length }, nodes, commits, edges, channel, lanesBottom,
    moreCommits: dto.map.more_commits,
  };
}

// Nodos y commits relacionados con una selección (`step:<id>` o `commit:<sha>`).
export function relatedTo(layout, sel) {
  if (!sel) return null;
  const related = new Set([sel]);
  for (const node of layout.nodes) {
    if (node.kind === "group" && node.members.includes(sel)) related.add(node.id);
  }
  // Un paso trae sus commits y, por ellos, los otros pasos que los citan (§21.6: "¿qué otro
  // paso citó este commit?"); un commit trae sus pasos citantes.
  const commits = new Set(sel.startsWith("commit:") ? [sel] : []);
  for (const edge of layout.edges) {
    if (edge.step === sel || edge.source === sel) commits.add(edge.target);
  }
  for (const edge of layout.edges) {
    if (commits.has(edge.target)) related.add(edge.source).add(edge.step).add(edge.target);
  }
  return related;
}

function stepLabel(node) {
  const parts = [`Paso ${node.idx}`, STATE_LABEL[node.state] ?? node.state, `carril ${agentLabel(node.lane)}`];
  if (node.secondary.length) parts.push(`también ${node.secondary.map(agentLabel).join(", ")}`);
  if (node.alignments) parts.push(`${node.alignments} alineamientos`);
  if (node.deviations) parts.push(`${node.deviations} desvíos`);
  if (node.runs) parts.push(`${node.runs} runs`);
  if (node.singleCommits) parts.push(`${node.singleCommits} commits citados sin compartir`);
  return parts.join(", ");
}

// SVG del mapa. Cada paso, grupo y commit es enfocable (`tabindex`) con nombre accesible y
// `data-sel` / `data-group` para la delegación de la vista.
export function renderMap(layout) {
  const L = LAYOUT;
  const lanes = layout.lanes.map((lane) => svg("g", { class: "map-lane" },
    svg("rect", { class: "map-lane-bg", x: 0, y: lane.y - 8, width: layout.width, height: L.lane - 8, rx: 6 }),
    svg("text", { class: "map-lane-label", x: 10, y: lane.y + L.nodeHeight / 2 + 4 }, lane.label)));
  const edges = layout.edges.map((edge) => svg("path", {
    class: ["map-edge", edge.shared && "is-shared"], d: edge.d, data: { from: edge.source, to: edge.target },
  }));
  const ghosts = layout.nodes.filter((node) => node.kind === "step").flatMap((node) => node.ghosts.map((ghost) =>
    svg("rect", { class: "map-ghost", x: node.x + 6, y: ghost.y + 6, width: L.nodeWidth - 12, height: L.nodeHeight - 12, rx: 6,
      data: { owner: node.id } })));
  const nodes = layout.nodes.map((node) => {
    if (node.kind === "group") {
      return svg("g", { class: "map-node map-group", tabindex: 0, role: "button", data: { group: node.id, node: node.id },
        "aria-label": `${node.label}, agrupados (${node.sub}). Enter para expandir.` },
      svg("rect", { x: node.x, y: node.y, width: L.nodeWidth, height: L.nodeHeight, rx: 8 }),
      svg("text", { x: node.x + 10, y: node.y + 17 }, node.label),
      svg("text", { class: "map-sub", x: node.x + 10, y: node.y + 31 }, node.sub));
    }
    const facts = [node.alignments ? `${node.alignments}a` : null, node.runs ? `${node.runs}r` : null,
      node.singleCommits ? `◇${node.singleCommits}` : null].filter(Boolean).join(" ");
    return svg("g", {
      class: ["map-node", "map-step", `is-${node.state.replace(/_/g, "-")}`], tabindex: 0, role: "button",
      data: { sel: node.id, node: node.id, column: node.column }, "aria-label": stepLabel(node),
    },
    svg("rect", { x: node.x, y: node.y, width: L.nodeWidth, height: L.nodeHeight, rx: 8 }),
    svg("text", { x: node.x + 10, y: node.y + 17 }, `${node.symbol} Paso ${node.idx}`),
    facts ? svg("text", { class: "map-sub", x: node.x + 10, y: node.y + 31 }, facts) : null,
    node.deviations ? svg("circle", { class: "map-deviation", cx: node.x + L.nodeWidth - 10, cy: node.y + 10, r: 5 }) : null,
    node.badges.length ? svg("text", { class: "map-badge", x: node.x + L.nodeWidth - 12, y: node.y + 33 }, node.badges.join("")) : null);
  });
  const commits = layout.commits.map((commit) => {
    const s = L.commitSize;
    return svg("g", {
      class: ["map-node", "map-commit", commit.shared && "is-shared"], tabindex: 0, role: "button",
      data: { sel: commit.id, node: commit.id },
      "aria-label": `Commit ${commit.label}${commit.shared ? ", compartido por varios pasos" : ""}`
        + `${commit.hidden ? `, ${commit.hidden} citas más sin dibujar` : ""}`,
    },
    svg("path", { d: `M ${commit.x} ${commit.y - s} L ${commit.x + s} ${commit.y} L ${commit.x} ${commit.y + s} L ${commit.x - s} ${commit.y} Z` }),
    svg("text", { x: commit.x + s + 6, y: commit.y + 4 }, commit.hidden ? `${commit.label} +${commit.hidden}` : commit.label));
  });
  const strip = layout.commits.length
    ? svg("text", { class: "map-strip-label", x: 10, y: layout.channel + 22 }, "Commits")
    : null;
  return svg("svg", {
    class: "context-map", viewBox: `0 0 ${layout.width} ${layout.height}`, width: layout.width, height: layout.height,
    role: "group", "aria-label": "Mapa de los pasos del contexto por agente y commits citados",
  }, lanes, strip, edges, ghosts, nodes, commits);
}

// Atenúa lo no relacionado con `sel` y marca lo seleccionado, sin regenerar el SVG.
export function select(root, layout, sel) {
  const related = relatedTo(layout, sel);
  for (const element of root.querySelectorAll("[data-node], [data-from], [data-owner]")) {
    const id = element.getAttribute("data-node") ?? element.getAttribute("data-owner");
    const from = element.getAttribute("data-from");
    const to = element.getAttribute("data-to");
    const isRelated = !related || (id ? related.has(id) : related.has(from) && related.has(to));
    element.classList.toggle("is-dim", !isRelated);
    element.classList.toggle("is-selected", Boolean(sel) && id === sel);
    if (id && element.getAttribute("role") === "button") element.setAttribute("aria-pressed", String(Boolean(sel) && id === sel));
  }
}

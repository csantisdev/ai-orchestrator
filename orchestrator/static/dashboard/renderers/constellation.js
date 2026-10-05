// Representación Constelación de los contextos del proyecto (spec §22.4, maqueta v6): soles
// por contexto (tamaño según sus pasos), satélites por paso, puentes por commits compartidos
// (grosor según cuántos) y portales hacia otros proyectos. Las posiciones vienen del servidor
// (deterministas); acá solo se filtra por alcance y modo, y se dibuja. `layoutConstellation`
// es puro; `selectConstellation` atenúa por clases sin regenerar el SVG.

import { svg } from "../core/dom.js";

const AGENTS = { claude: "Claude", codex: "Codex", copilot: "Copilot", otros: "Otros", "sin agente": "Sin agente" };
const STATES = { active: "activo", programado: "programado", completed: "completado", abandoned: "abandonado" };
const MAX_SATELLITES = 24;
const GRID_COLUMNS = 10;

export function agentLabel(agent) {
  return AGENTS[agent] ?? agent;
}

// Radio del sol: crece con la raíz de la cantidad de pasos.
export function sunRadius(steps) {
  return Math.round(14 + 4 * Math.sqrt(Math.max(steps, 0)));
}

// Vecinos de un contexto por puentes, hasta `depth` saltos (modo local, §22.4).
export function neighborhood(bridges, focus, depth) {
  const seen = new Set([focus]);
  let frontier = [focus];
  for (let level = 0; level < depth; level += 1) {
    const next = [];
    for (const bridge of bridges) {
      for (const [from, to] of [[bridge.source, bridge.target], [bridge.target, bridge.source]]) {
        if (frontier.includes(from) && !seen.has(to)) {
          seen.add(to);
          next.push(to);
        }
      }
    }
    frontier = next;
  }
  return seen;
}

// Qué se dibuja según el alcance (activos y conectados a ellos, o todos) y el modo (global o
// local alrededor del contexto seleccionado).
export function layoutConstellation(dto, { scope = "active", mode = "global", focus = null, depth = 1, lens = "agent" } = {}) {
  const c = dto.constellation;
  const contexts = dto.nodes.filter((node) => node.kind === "context");
  const portals = dto.nodes.filter((node) => node.kind === "portal");
  const steps = dto.nodes.filter((node) => node.kind === "step");
  let visible;
  if (mode === "local" && focus && contexts.some((node) => node.id === focus)) {
    visible = neighborhood(c.bridges, focus, depth);
  } else if (scope === "all") {
    visible = new Set([...contexts, ...portals].map((node) => node.id));
  } else {
    const active = new Set(contexts.filter((node) => node.state === "active").map((node) => node.id));
    visible = new Set(active);
    for (const bridge of c.bridges) {
      if (active.has(bridge.source) || active.has(bridge.target)) {
        visible.add(bridge.source);
        visible.add(bridge.target);
      }
    }
  }
  const satellitesOf = new Map();
  for (const node of steps) {
    const owner = node.attrs.context;
    if (!satellitesOf.has(owner)) satellitesOf.set(owner, []);
    satellitesOf.get(owner).push(node);
  }
  // Los aislados visibles se reacomodan en la grilla sin huecos (mismo orden que el servidor).
  const isolatedVisible = c.isolated.filter((id) => visible.has(id));
  const gridTop = Math.min(...c.isolated.map((id) => c.positions[id].y));
  const gap = (c.size.width - 120) / (GRID_COLUMNS - 1);
  const positionOf = (id) => {
    const index = isolatedVisible.indexOf(id);
    if (index < 0 || isolatedVisible.length === c.isolated.length) return c.positions[id];
    return { x: +(60 + (index % GRID_COLUMNS) * gap).toFixed(2), y: gridTop + Math.floor(index / GRID_COLUMNS) * 90 };
  };
  const suns = contexts.filter((node) => visible.has(node.id)).map((node) => {
    const position = positionOf(node.id);
    const radius = sunRadius(node.attrs.steps);
    const satellites = (satellitesOf.get(node.id) ?? []).slice(0, MAX_SATELLITES).map((step, index, all) => {
      const angle = (2 * Math.PI * index) / Math.max(all.length, 1) - Math.PI / 2;
      return { id: step.id, lane: step.attrs.lane, state: step.state,
        x: +(position.x + Math.cos(angle) * (radius + 10)).toFixed(2), y: +(position.y + Math.sin(angle) * (radius + 10)).toFixed(2) };
    });
    return {
      id: node.id, label: node.label, state: node.state, x: position.x, y: position.y, radius,
      steps: node.attrs.steps, inProgress: node.attrs.in_progress, deviations: node.attrs.deviations,
      agent: node.attrs.agent, connected: node.attrs.connected, isolated: c.isolated.includes(node.id),
      tone: lens === "project" ? "project" : node.attrs.agent, satellites,
    };
  });
  const portalNodes = portals.filter((node) => visible.has(node.id)).map((node) => ({
    id: node.id, label: node.label, commits: node.attrs.commits, x: c.positions[node.id].x, y: c.positions[node.id].y,
  }));
  const placed = new Set([...suns, ...portalNodes].map((node) => node.id));
  const bridges = c.bridges.filter((bridge) => placed.has(bridge.source) && placed.has(bridge.target)).map((bridge) => ({
    ...bridge,
    from: c.positions[bridge.source], to: c.positions[bridge.target],
    width: +(1.5 + Math.log2(1 + bridge.weight) * 1.5).toFixed(2),
  }));
  // Caja de dibujo ajustada a lo visible (con un mínimo para que pocos soles no se agranden de más).
  const points = [...suns.map((sun) => [sun.x, sun.y, sun.radius + 24]), ...portalNodes.map((portal) => [portal.x, portal.y, 60])];
  let box = [0, 0, c.size.width, 200];
  if (points.length) {
    const minX = Math.min(...points.map(([px, , r]) => px - r));
    const minY = Math.min(...points.map(([, py, r]) => py - r));
    const width = Math.max(...points.map(([px, , r]) => px + r)) - minX;
    const height = Math.max(...points.map(([, py, r]) => py + r)) - minY;
    const fullWidth = Math.max(width, 360);
    const fullHeight = Math.max(height, 180);
    box = [minX - (fullWidth - width) / 2, minY - (fullHeight - height) / 2, fullWidth, fullHeight].map((n) => +n.toFixed(2));
  }
  return {
    suns, portals: portalNodes, bridges, viewBox: box,
    hiddenContexts: contexts.length - suns.length,
  };
}

// Lo relacionado con la selección: un contexto o portal y sus vecinos por puentes; un commit,
// los extremos de los puentes que lo comparten.
export function constellationRelated(layout, sel) {
  if (!sel) return null;
  const related = new Set([sel]);
  for (const bridge of layout.bridges) {
    if (bridge.commits.includes(sel)) {
      related.add(bridge.source);
      related.add(bridge.target);
    }
    if (bridge.source === sel) related.add(bridge.target);
    if (bridge.target === sel) related.add(bridge.source);
  }
  return related;
}

function sunLabel(sun) {
  const parts = [sun.label, STATES[sun.state] ?? sun.state, `${sun.steps} pasos`, `agente dominante ${agentLabel(sun.agent)}`];
  if (sun.inProgress) parts.push(`${sun.inProgress} en curso`);
  if (sun.deviations) parts.push(`${sun.deviations} desvíos`);
  parts.push(sun.connected ? "comparte commits con otros contextos" : "sin conexiones");
  return parts.join(", ");
}

// SVG de la constelación. `interactive: false` para la vista previa de Inicio (sin foco ni roles).
export function renderConstellation(layout, { interactive = true } = {}) {
  const [x, y, width, height] = layout.viewBox;
  const focusable = (props) => (interactive ? { ...props, tabindex: 0, role: "button", "aria-pressed": "false" } : props);
  const bridges = layout.bridges.map((bridge) => svg("line", {
    class: ["cons-bridge", bridge.portal && "is-portal"], x1: bridge.from.x, y1: bridge.from.y, x2: bridge.to.x, y2: bridge.to.y,
    "stroke-width": bridge.width, data: { from: bridge.source, to: bridge.target },
  }, svg("title", {}, `${bridge.weight} ${bridge.weight === 1 ? "commit compartido" : "commits compartidos"}`)));
  const suns = layout.suns.map((sun) => svg("g", focusable({
    class: ["cons-sun", `tone-${sun.tone.replace(/\s+/g, "-")}`, sun.inProgress && "is-live", sun.deviations && "has-deviation"],
    data: { sel: sun.id, node: sun.id }, "aria-label": sunLabel(sun),
  }),
  sun.inProgress ? svg("circle", { class: "cons-halo", cx: sun.x, cy: sun.y, r: sun.radius + 8 }) : null,
  sun.satellites.map((sat) => svg("circle", { class: ["cons-satellite", `tone-${sat.lane.replace(/\s+/g, "-")}`, sat.state === "in_progress" && "is-live"],
    cx: sat.x, cy: sat.y, r: 3 })),
  svg("circle", { class: "cons-core", cx: sun.x, cy: sun.y, r: sun.radius }),
  svg("text", { class: "cons-id", x: sun.x, y: sun.y - 2, "text-anchor": "middle" }, `#${sun.id.split(":")[1]}`),
  svg("text", { class: "cons-agent", x: sun.x, y: sun.y + 11, "text-anchor": "middle" }, agentLabel(sun.agent))));
  // El portal es informativo: sus commits se recorren desde la lista de puentes.
  const portals = layout.portals.map((portal) => svg("g", {
    class: "cons-portal", data: { node: portal.id, portal: portal.label }, role: "img",
    "aria-label": `Portal a ${portal.label}: ${portal.commits} commits compartidos con este proyecto`,
  },
  svg("rect", { x: portal.x - 56, y: portal.y - 12, width: 112, height: 24, rx: 12 }),
  svg("text", { x: portal.x, y: portal.y + 4, "text-anchor": "middle" }, `↗ ${portal.label} · ${portal.commits}`)));
  return svg("svg", {
    class: ["constellation", !interactive && "is-preview"], viewBox: `${x} ${y} ${width} ${height}`,
    role: interactive ? "group" : "img",
    "aria-label": interactive
      ? "Constelación de los contextos del proyecto: contextos, pasos y commits compartidos"
      : "Vista previa de la constelación del proyecto",
  }, bridges, portals, suns);
}

// Atenúa lo que no se relaciona con `sel` y marca lo seleccionado.
export function selectConstellation(root, layout, sel) {
  const related = constellationRelated(layout, sel);
  for (const element of root.querySelectorAll("[data-node], [data-from]")) {
    const id = element.getAttribute("data-node");
    const isRelated = !related || (id ? related.has(id)
      : related.has(element.getAttribute("data-from")) && related.has(element.getAttribute("data-to")));
    element.classList.toggle("is-dim", !isRelated);
    element.classList.toggle("is-selected", Boolean(sel) && id === sel);
    if (id && element.getAttribute("data-sel")) element.setAttribute("aria-pressed", String(Boolean(sel) && id === sel));
  }
}

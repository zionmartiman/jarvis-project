/*
 * Pure functions that keep the memory graph in the browser. The same applyEvent runs on live
 * events and when the history is replayed, so both always agree with the server.
 *
 * State: { version, nodes: Map<id, node>, links: Map<id, link> }. Nodes and links are the JSON
 * objects of the API (links keep numeric source/target ids, never node references).
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.GraphState = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function createState() {
    return { version: 0, nodes: new Map(), links: new Map() };
  }

  function fromSnapshot(snapshot) {
    var state = createState();
    state.version = snapshot.version;
    snapshot.nodes.forEach(function (node) {
      state.nodes.set(node.id, Object.assign({}, node));
    });
    snapshot.links.forEach(function (link) {
      state.links.set(link.id, Object.assign({}, link));
    });
    return state;
  }

  function copyInto(map, id, data) {
    var existing = map.get(id);
    if (existing) {
      Object.assign(existing, data);
    } else {
      map.set(id, Object.assign({}, data));
    }
  }

  /**
   * Apply one event ({version, op, data}) to the state and return what changed:
   * {nodeIds, linkIds, removedNodeIds, removedLinkIds}. Events at or before the state's version
   * are ignored (the snapshot and the stream can overlap after a reconnection).
   */
  function applyEvent(state, event) {
    var changes = { nodeIds: [], linkIds: [], removedNodeIds: [], removedLinkIds: [] };
    if (event.version <= state.version) {
      return changes;
    }
    var data = event.data;
    switch (event.op) {
      case "entity_created":
      case "entity_updated":
        copyInto(state.nodes, data.id, data);
        changes.nodeIds.push(data.id);
        break;
      case "relation_created":
      case "relation_updated":
        copyInto(state.links, data.id, data);
        changes.linkIds.push(data.id);
        break;
      case "relation_invalidated": {
        var link = state.links.get(data.id);
        if (link) {
          link.valid_to = data.valid_to;
          link.invalidation_reason = data.reason;
          changes.linkIds.push(data.id);
        }
        break;
      }
      case "entity_merged":
        // The links that were moved arrived earlier as relation_updated. The ones that still
        // point at the merged entity joined the two merged entities (or were duplicates).
        state.nodes.delete(data.from_id);
        changes.removedNodeIds.push(data.from_id);
        copyInto(state.nodes, data.into.id, data.into);
        changes.nodeIds.push(data.into.id);
        Array.from(state.links.values()).forEach(function (candidate) {
          if (candidate.source === data.from_id || candidate.target === data.from_id) {
            state.links.delete(candidate.id);
            changes.removedLinkIds.push(candidate.id);
          }
        });
        break;
      default:
        break; // an operation from a newer server: skip it but keep the version moving
    }
    state.version = event.version;
    return changes;
  }

  /** A state rebuilt from the first `count` events, starting from nothing. */
  function stateAt(events, count) {
    var state = createState();
    for (var index = 0; index < count && index < events.length; index += 1) {
      applyEvent(state, events[index]);
    }
    return state;
  }

  /**
   * The {nodes, links} for force-graph. Node and link view objects are kept in `cache`
   * ({nodes: Map, links: Map}) and reused, so force-graph keeps the positions it computed
   * (also for a node that leaves and comes back while the history is scrubbed).
   * Expired links are left out unless options.showExpired is set, and so are links whose ends
   * are not both in the state. `degree` counts the current links of each node.
   */
  function toGraphData(state, options, cache) {
    var showExpired = Boolean(options && options.showExpired);
    var degree = new Map();
    var links = [];
    state.links.forEach(function (link) {
      if (!state.nodes.has(link.source) || !state.nodes.has(link.target)) return;
      if (link.valid_to && !showExpired) return;
      if (!link.valid_to) {
        degree.set(link.source, (degree.get(link.source) || 0) + 1);
        degree.set(link.target, (degree.get(link.target) || 0) + 1);
      }
      var view = cache.links.get(link.id);
      if (view) {
        Object.assign(view, link);
      } else {
        view = Object.assign({}, link);
        cache.links.set(link.id, view);
      }
      links.push(view);
    });

    var nodes = [];
    state.nodes.forEach(function (node) {
      var view = cache.nodes.get(node.id);
      if (view) {
        Object.assign(view, node);
      } else {
        view = Object.assign({}, node);
        cache.nodes.set(node.id, view);
      }
      view.degree = degree.get(node.id) || 0;
      nodes.push(view);
    });
    return { nodes: nodes, links: links };
  }

  function createCache() {
    return { nodes: new Map(), links: new Map() };
  }

  return {
    createState: createState,
    fromSnapshot: fromSnapshot,
    applyEvent: applyEvent,
    stateAt: stateAt,
    toGraphData: toGraphData,
    createCache: createCache,
  };
});

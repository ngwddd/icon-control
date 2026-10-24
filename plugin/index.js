/**
 * Host half of the mouse-permission bundle.
 *
 * The switch itself lives entirely in the browser (see client.js): it is a
 * user-only authority control, so no host service method or agent tool grants
 * it — the agent may read the state, never set it.
 */
export function apply() {}

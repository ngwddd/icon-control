"""Additive result taxonomy. Legacy ok/success/status/verdict stay intact."""
from __future__ import annotations

OUTCOMES = frozenset({'verified_success', 'executed_unverified', 'refused',
                      'failed', 'cancelled', 'observed'})
REFUSAL_CODES = frozenset({
    'permission_denied', 'authority_unavailable', 'invalid_argument', 'invalid_index',
    'ambiguous', 'ambiguous_target', 'offscreen_target', 'out_of_screen',
    'target_occluded', 'target_unverified', 'target_changed', 'stale_element',
    'text_not_found', 'pointer_contract_unsupported', 'no_target', 'focus_failed',
})
MUTATIONS = frozenset({'input', 'text_entry', 'window', 'window_close', 'compose',
                       'process', 'clipboard_write', 'file_write', 'file_delete',
                       'config_write', 'control'})


def normalize(result, tool=None, arguments=None):
    if not isinstance(result, dict):
        return result
    body = dict(result)
    supplied = body.get('outcome')
    known_tool = False
    effects = set()
    if tool:
        from computer_mcp import tool_registry
        spec = tool_registry.get(tool)
        if spec:
            known_tool = True
            try:
                effects = set(spec.effects_for(arguments))
            except (ValueError, TypeError):
                # Never erase execution evidence if classification fails.
                effects = MUTATIONS
    mutation = bool(effects & MUTATIONS)
    if (body.get('dry_run') is True
            or isinstance(arguments, dict) and arguments.get('dry_run') is True):
        mutation = False
    code = body.get('code')
    failure = (bool(body.get('error')) or body.get('ok') is False
               or body.get('success') is False or body.get('matched') is False
               or body.get('status') == 'no_effect'
               or body.get('verification') == 'no_effect')
    if supplied == 'cancelled' or body.get('cancelled') or code == 'execution_cancelled':
        outcome = 'cancelled'
    elif supplied == 'refused' or body.get('blocked') or (failure and code in REFUSAL_CODES):
        outcome = 'refused'
    elif supplied == 'failed' or failure:
        outcome = 'failed'
    elif (body.get('verified') is True
          or body.get('status') in ('verified_success', 'verified_absent')
          or body.get('verification') == 'verified_success'):
        outcome = 'verified_success'
    else:
        if (body.get('status') == 'executed_unverified' or mutation
                or supplied == 'executed_unverified' or not known_tool):
            outcome = 'executed_unverified'
            body.setdefault('verified', False)
        else:
            # Read completion has a separate status: it is not a verified effect.
            outcome = 'observed'
            body.setdefault('verification_scope', 'tool_completion')
    body['outcome'] = outcome
    if tool:
        body['tool'] = tool
        body['action_category'] = 'mutation' if mutation else 'observation' if known_tool else 'unknown'
    return body

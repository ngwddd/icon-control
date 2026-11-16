"""Additive result taxonomy. Legacy ok/success/status/verdict stay intact."""
from __future__ import annotations

OUTCOMES = frozenset({'verified_success', 'executed_unverified', 'refused',
                      'failed', 'cancelled'})
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
    if body.get('outcome') in OUTCOMES:
        return body
    code = body.get('code')
    failure = (bool(body.get('error')) or body.get('ok') is False
               or body.get('success') is False or body.get('matched') is False
               or body.get('status') == 'no_effect'
               or body.get('verification') == 'no_effect')
    if body.get('cancelled') or code == 'execution_cancelled':
        outcome = 'cancelled'
    elif body.get('blocked') or (failure and code in REFUSAL_CODES):
        outcome = 'refused'
    elif failure:
        outcome = 'failed'
    elif (body.get('verified') is True
          or body.get('status') in ('verified_success', 'verified_absent')
          or body.get('verification') == 'verified_success'):
        outcome = 'verified_success'
    else:
        effects = set()
        if tool:
            from computer_mcp import tool_registry
            spec = tool_registry.get(tool)
            if spec:
                try:
                    effects = set(spec.effects_for(arguments))
                except (ValueError, TypeError):
                    # Classification must not erase evidence after execution.
                    effects = MUTATIONS
        mutation = bool(effects & MUTATIONS)
        if (body.get('dry_run') is True
                or isinstance(arguments, dict) and arguments.get('dry_run') is True):
            mutation = False
        if body.get('status') == 'executed_unverified' or mutation:
            outcome = 'executed_unverified'
            body.setdefault('verified', False)
        else:
            outcome = 'verified_success'
            # Completion of an observation is not evidence of a business action.
            body.setdefault('verification_scope', 'tool_completion')
    body['outcome'] = outcome
    return body

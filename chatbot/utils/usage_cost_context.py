# Purpose:  Thread/coroutine-safe context propagation for the active chat turn's
#           session and profile IDs. Allows llm_script.py to attribute LLM costs
#           to a ChatSession without passing IDs through every function in the chain
#           (ChatOrchestrator → FreeFlowService → llm_models → llm_script).
#           Safe for both threading (Django/Celery) and async (asyncio) contexts
#           because Python's contextvars are isolated per coroutine/thread.
import contextvars

# Carries (session_id, profile_id) for the chat turn currently being processed by
# ChatOrchestrator/FreeFlowService, so llm_models/llm_script.py can attribute LLM
# cost to a ChatSession without threading these IDs through every handler signature.
_usage_cost_context = contextvars.ContextVar('usage_cost_context', default=None)


# Purpose: Sets context for the current turn.
# Output:  Reset token — must be passed to reset_usage_cost_context() in a
#          finally block to prevent context leaking into subsequent requests.
def set_usage_cost_context(session_id, profile_id=None):
    token = _usage_cost_context.set({'session_id': session_id, 'profile_id': profile_id})
    return token


# Purpose: Returns {session_id, profile_id} dict for the current turn, or None.
def get_usage_cost_context():
    return _usage_cost_context.get()


# Purpose: Clears the context. Must be called in a finally block to prevent leaks.
def reset_usage_cost_context(token):
    _usage_cost_context.reset(token)

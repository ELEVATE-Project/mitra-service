# Mohini Service

Chat bot platform where a company's conversational flow is modeled as an ordered sequence of state machine steps, each answered by either an LLM or a fixed non-LLM handler.

## Language

**Operation Type**:
Per-step classification on `CompanyStateMachine.operation_type`: either `LLM` (dynamically generated response) or `NON_LLM` (fixed/scripted response). Only these two values exist.

**LLM-skip rule**:
During bulk generation (`generate_state_machine_translations` or `generate_state_machine_audio` with no `state_machine_id`), a step whose Operation Type is `LLM` is skipped (existing cached `translations` left untouched) when its predecessor (`step - 1`) is also `LLM`, but generated when the predecessor is `NON_LLM`. Rationale: only the first `LLM` step after a `NON_LLM` step needs pre-generated translations/audio; consecutive `LLM` steps answer dynamically and don't need them. A step with no predecessor (lowest step) that is `LLM` is always skipped. Translation generation and audio generation are separate tasks (audio is not currently wired to any caller) but share this rule via a common helper.

**Revoke Audio**:
The "Revoke Audio" inline action (`revoke_state_machine_audio`) deletes every cached `audio_s3` file for a `CompanyStateMachine` row from S3 and strips `audio_s3` from `translations` for each language, all in one synchronous admin request (unlike generate, which is async via Celery). A language whose S3 delete fails keeps its `audio_s3` entry untouched, so a retry only re-attempts the failed languages. A language left with no other keys after stripping `audio_s3` is dropped from `translations` entirely rather than left as `{}`.

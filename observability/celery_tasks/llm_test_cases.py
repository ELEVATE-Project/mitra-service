from celery import shared_task
from chatbot.utils.llm import LLM
from observability.utils.preparechats import get_chat_dict
from observability.models.enums import TestCaseInputFormat, TCRunMetrics, TCStatus
from chatbot.models import CompanyBot, LLMProvider
from chatbot.utils.env_parser import load_env_to_dict
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, ContextualPrecisionMetric, ContextualRecallMetric, ContextualRelevancyMetric, BiasMetric, ToxicityMetric, SummarizationMetric, PromptAlignmentMetric, HallucinationMetric
from observability.utils.deepeval import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase
import json
from django.db.models import Avg


def execute_test_case(
    test_case,
    model: str,
    deepeval_llm_model: str,
    deepeval_llm_provider: str,
    provider: str,
    system_prompt: str,
    tc_run_id: int,
    temperature: str = None,
    provider_keys: str = None,
):

    # dynamic imports due to circular dependencies
    from observability.models import CompanyBotTCRun, TCBotRunMetrics, BotRunTestCaseMap

    metrics_val = {}
    deepeval_model_name = deepeval_llm_model

    if deepeval_llm_provider != LLMProvider.OPENAI:
        deepeval_model_name = deepeval_llm_provider + "/" + deepeval_llm_model

    deepeval_model = DeepEvalBaseLLM(model=deepeval_model_name)

    metrics_threshold = {}

    eval_metrics = list(TCBotRunMetrics.objects.filter(
        bot_tc_run=test_case.pk).all())
    for metric in eval_metrics:
        metrics_threshold[metric.metric_name] = metric.metric_threshold_value
        metric_args = {
            "threshold": metric.metric_threshold_value,
            "model": deepeval_model,
            "include_reason": True
        }
        if metric.metric_name == TCRunMetrics.ANSWER_RELEVANCY:
            metrics_val[metric.metric_name] = AnswerRelevancyMetric(
                **metric_args)

        elif metric.metric_name == TCRunMetrics.FAITHFULLNESS:
            metrics_val[metric.metric_name] = FaithfulnessMetric(**metric_args)

        elif metric.metric_name == TCRunMetrics.CONTEXTUAL_PRECISION:
            metrics_val[metric.metric_name] = ContextualPrecisionMetric(
                **metric_args)

        elif metric.metric_name == TCRunMetrics.CONTEXTUAL_RECALL:
            metrics_val[metric.metric_name] = ContextualRecallMetric(
                **metric_args)

        elif metric.metric_name == TCRunMetrics.CONTEXTUAL_RELEVANCY:
            metrics_val[metric.metric_name] = ContextualRelevancyMetric(
                **metric_args)

        elif metric.metric_name == TCRunMetrics.BIAS:
            metrics_val[metric.metric_name] = BiasMetric(
                **metric_args)

        elif metric.metric_name == TCRunMetrics.TOXICITY:
            metrics_val[metric.metric_name] = ToxicityMetric(
                **metric_args)

        elif metric.metric_name == TCRunMetrics.SUMMARIZATION:
            metrics_val[metric.metric_name] = SummarizationMetric(
                **metric_args, assessment_questions=metric.assessment_questions)

        elif metric.metric_name == TCRunMetrics.PROMPT_ALLIGNMENT:
            metrics_val[metric.metric_name] = PromptAlignmentMetric(
                model=deepeval_model,
                prompt_instructions=metric.prompt_instructions,
                threshold=metric.metric_threshold_value
            )

        elif metric.metric_name == TCRunMetrics.HALLUCINATION:
            metrics_val[metric.metric_name] = HallucinationMetric(
                **metric_args)

        # need to do: Add JSON Relevency metric as well
        else:
            pass

    llm = LLM(
        model=model,
        provider=provider,
        temperature=temperature,
        llm_env_conf=load_env_to_dict(provider_keys)
    )

    testcase_input = test_case.testcase_input
    test_case_message = []
    if test_case.input_format == TestCaseInputFormat.JSON:
        try:
            if test_case.chat_session is not None:
                test_case_message = get_chat_dict(test_case.chat_session)
            else:
                test_case_message = json.loads(test_case.message)

            test_case_message = [{
                "role": "system",
                "content": system_prompt
            }] + test_case_message
        except Exception as e:
            print("Invalid JSON received for test case: ", test_case.pk)
            pass

    test_case_llm = LLMTestCase(
        input=testcase_input,
        actual_output=llm.prompt(test_case_message).choices[0].message.content,
        expected_output=test_case.expected_output,
        retrieval_context=test_case.retrieval_context.split("\n"),
    )

    try:
        for metric in metrics_val:
            print("Running metric evaluation for --> " + metric)
            metrics_val[metric].measure(test_case_llm)
            print(metrics_val[metric].reason, "<< REASON")
            print(metrics_val[metric].score, "<< SCORE")
            print(metrics_val[metric])
            run_tc_map = BotRunTestCaseMap(
                bot_run=CompanyBotTCRun(pk=tc_run_id),
                test_case=test_case,
                metric_name=metric,
                score=metrics_val[metric].score,
                reason=metrics_val[metric].reason,
                status=TCStatus.PASS if metrics_val[metric].is_successful(
                ) else TCStatus.FAILED
            )
            run_tc_map.save()
    except Exception as e:
        print(e)

    print(list(metrics_val.keys()))

    print(eval_metrics, len(eval_metrics), "Eval Metrics printed")


@shared_task
def run(company_bot_id: int, tc_run_id: int):

    # dynamic imports due to circular dependencies
    from observability.models import CompanyBotTestCases, CompanyBotTCRun, TCBotRunMetrics, BotRunTestCaseMap
    from observability.models.enums import TCRunStatus

    company_bot = CompanyBot.objects.get(pk=company_bot_id)
    bot_tc_run = CompanyBotTCRun.objects.get(pk=tc_run_id)
    company_test_cases = list(CompanyBotTestCases.objects.filter(
        company_bot=CompanyBot(pk=company_bot_id)
    ).all())

    print(company_test_cases)
    # loads the test cases
    for test_case in company_test_cases:
        execute_test_case(
            test_case,
            model=company_bot.llm_model,
            provider=company_bot.provider,
            temperature=company_bot.bot_temperature,
            provider_keys=company_bot.provider_keys,
            system_prompt=company_bot.context,
            tc_run_id=tc_run_id,
            deepeval_llm_model=bot_tc_run.llm_model,
            deepeval_llm_provider=bot_tc_run.provider,
        )
        # NOTE:
        # solution
        # DONE: deepeval llm terminologies
        # DONE: threshold to be exposed to db
        # DONE: test cases metrics should be customizable
        # DONE: metric scores to be stored in the db
        # DONE: metric should be at test case level
        # DONE: chat session to be added to TC Run Test Case (prepare messages for chat sessions)
        # DONE: test case pass fail status
        # need to do: Verifier and checker company bot and testing
        # need to do: Langfuse integration with observability
        # need to do: if  test cases fail how to improve it??

    results = BotRunTestCaseMap.objects.filter(
        bot_run=CompanyBotTCRun(pk=tc_run_id)
    ).values('metric_name').annotate(avg_score=Avg('score'))

    tc_avg_results = {}

    for res in results:
        print("Final Results...")
        print(res["avg_score"], res["metric_name"])
        tc_avg_results[res["metric_name"]] = res["avg_score"]

    bot_tc_run.status = TCRunStatus.COMPLETED
    bot_tc_run.metrics_result = json.dumps(tc_avg_results)
    bot_tc_run.save()

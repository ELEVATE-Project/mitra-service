import requests
import os
from typing import List
from chatbot.llm_models.llm_script import handle_bedrock_model

DATABASE_INTERFACE_BEARER_TOKEN = os.getenv('DATABASE_INTERFACE_BEARER_TOKEN')


def query_database(query_prompt: str, priority_filter: str, limit: int):
    """
    Query vector database to retrieve chunk with user's input questions.
    """
    url = "http://13.202.158.115:8000/query/"
    headers = {
        "Content-Type": "application/json",
        "accept": "application/json",
    }
    data = {
        "query": query_prompt,
        "search_limit": limit,
    }
    if priority_filter:
        data["priority_filter"] = priority_filter
    print("DATA: ", data)
    response = requests.post(url, json=data, headers=headers)

    if response.status_code == 200:
        result = response.json()
        # process the result
        return result
    else:
        print(f"Error: {response.status_code} : {response.content}")


def apply_prompt_template(question: str) -> str:
    """
        A helper function that applies additional template on user's question.
        Prompt engineering could be done here to improve the result. Here I will just use a minimal example.
    """
    prompt = f"""
        Based on the above data (if applicable) please answer to following question/greeting: 
        {question}

        REMEMBER STRICTLY DO NOT PROVIDE ANY INFORMATION WHICH IS OUTSIDE OF CONTEXT AVAILABLE TO YOU.
    """
    return prompt


def call_bedrock_api(prompt, messages, temperature, chunks: List[str]):
    """
    Call chatgpt api with user's question and retrieved chunks.
    """
    text_to_add = " Use the following chunks along with the other information provided to generate the output:\n"
    prompt[0]['text'] += text_to_add + ''.join(
        map(lambda chunk: f"\n{chunk}", chunks)
    )
    print(messages)

    response = handle_bedrock_model(
        system_prompt=prompt, messages=messages, max_token=2048,
        temperature=temperature
    )

    return response


def ask(messages, user_question, temperature, priority_filter, top_k, prompt):
    """
    Handle user's questions.
    """
    # chunks_response = query_database(query_prompt=user_question, priority_filter=priority_filter, limit=top_k)
    # print("chunks_response", chunks_response)
    # chunks = []
    # if chunks_response and chunks_response["relevant_texts"]:
    #     for result in chunks_response["relevant_texts"]:
    #         if (
    #                 "qdrant_recommendation_text" in result
    #                 and result["qdrant_recommendation_text"] is not None
    #                 and len(result["qdrant_recommendation_text"]) > 20
    #         ):
    #             chunks.append(result["qdrant_recommendation_text"])
    #
    #         elif (
    #                 "translated_text" in result
    #                 and result["translated_text"] is not None
    #                 and len(result["translated_text"]) > 20
    #         ):
    #             chunks.append(result["translated_text"])
    # print("\nCHUNKS: ", chunks)
    chunks = []
    chunks_response = None
    response = call_bedrock_api(prompt=prompt, messages=messages, temperature=temperature, chunks=chunks)
    return response, chunks, chunks_response



def get_remaining_stage_prompt():
    prompt = """
    You are an assistant tasked with identifying which stages of a conversation have not been covered based on the 
    user's messages.

    **Stages and Their Questions:**

    1. **MAIN_CHALLENGE**:
       - **Primary Question:** "Namaste! I'm so excited to hear about your project. What challenge did you face in 
       your school or cluster?"
       - **Follow-up Questions:**
         1. "How did this challenge affect the students or teachers?"
         2. "What do you think was the root cause of the challenge?"
         3. Summarize the challenge that the user has shared.

    2. **DETAILED_STEPS**:
       - **Primary Question:** "Can you explain what steps you took to solve this challenge?"
       - **Follow-up Questions:**
         1. "Could you explain in detail how you carried out each step?"
         2. "What challenges did you face while carrying out these steps?"
         3. Summarize the detailed steps that the user has taken.

    3. **DURATION**:
       - **Primary Question:** "How long did it take to complete this micro improvement?"

    4. **TEAMWORK**:
       - **Primary Question:** "Please tell me about the team members who worked on this project."
       - **Follow-up Questions:**
         1. "[Optional] How did each team member contribute to the improvement?"

    5. **CHANGES**:
       - **Primary Question:** "What changes did you observe after completing the micro-improvement?"
       - **Follow-up Questions:**
         1. "Were there any highlights that you saw during the project?"

    6. **ADDITIONAL_INFORMATION**:
       - **Primary Question:** "Do you have any advice for others who might undertake similar projects?"
       - **Follow-up Questions:**
         1. "Are there aspects that could inform future projects or initiatives?"
         2. "Is there any additional information you would like to share about your experience?"
         3. "Were there any unexpected benefits or outcomes not covered in previous questions?"

    **Goal:**

    - Analyze the user's messages to determine which stages have been addressed. **Approximate matching is acceptable; 
    be very lenient.**

    **Task:**

    1. Review the user's messages.
    2. For each stage, check if the user has addressed **any** of the questions (primary or follow-up) associated with 
       that stage.
    3. **If the user's message includes any information related to a stage's questions, consider that stage as 
       covered, even if the information is brief or lacks detail.**
    4. Compile a list of stages that have **not** been covered.

    **Examples:**

    - **Example 1:**

      - **User's Message:** "We faced issues with student attendance. I organized community meetings to address this."

      - **Expected Output:**
        {
          "remaining_stages": ["DURATION", "TEAMWORK", "CHANGES", "ADDITIONAL_INFORMATION"]
        }

      - **Explanation:** The user mentioned organizing meetings; **DETAILED_STEPS** is considered covered due to leniency.

       - **Example 2:**

      - **User's Message:** "Hello! In our school, we faced a significant challenge where many students were struggling 
      with reading comprehension, which was affecting their overall academic performance and confidence levels. For 
      others considering similar projects, I advise starting by identifying the interests of your students to select 
      appropriate materials."

      - **Expected Output:**
        {
          "remaining_stages": ["DETAILED_STEPS", "DURATION", "TEAMWORK", "CHANGES"]
        }

      - **Explanation:** **ADDITIONAL_INFORMATION** is considered covered since the user provided advice for other 
      students.

    **Output Format:**

    Provide a VALID object in the following format:

    {
      "remaining_stages": ["MAIN_CHALLENGE", "DETAILED_STEPS", ...]
    }

    If all stages have been covered, return:

    {
      "remaining_stages": []
    }

    **Note:** Do not include any additional text or explanation in the output—only the object.
    """

    prompt_to_use = [
        {
            'text': prompt
        }
    ]

    return prompt_to_use

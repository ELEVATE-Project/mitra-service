from celery import shared_task

from chatbot.models import FileTypeChoices
from chatbot.scripts.knowledge_service.extraction.ai_extraction import get_doc_tags_from_ai
import os


@shared_task
def get_auto_extracted_data(file_path, company_bot_id=None, file_extension=None, other_data=None):
    from chatbot.models import CompanyBot

    company_bot = None
    if company_bot_id:
        try:
            company_bot = CompanyBot.objects.get(id=company_bot_id)
        except CompanyBot.DoesNotExist:
            pass

    extracted_data=None
    try:
        # extracted_data = get_doc_tags_from_ai(
        #     file=file_path,
        #     company_bot=company_bot,
        #     file_extension=file_extension,
        #     other_data=other_data
        # )
        extracted_data = {
          'title': 'House System – Design for Unity and Inclusivity in Schools',
          'organization': 'Vidhya Vidhai Foundation',
          'tags': [
            {
              'text': 'Student Voice',
              'source': 'extracted',
              'reason': "Explicitly listed in document's tags/keywords section",
              'description': ''
            },
            {
              'text': 'School Environment',
              'source': 'extracted',
              'reason': "Explicitly listed in document's tags/keywords section",
              'description': ''
            },
            {
              'text': 'Inclusivity',
              'source': 'extracted',
              'reason': "Explicitly listed in document's tags/keywords section",
              'description': ''
            },
            {
              'text': 'Education Leadership',
              'source': 'extracted',
              'reason': "Explicitly listed in document's tags/keywords section",
              'description': ''
            },
            {
              'text': 'Systems Change',
              'source': 'extracted',
              'reason': "Explicitly listed in document's tags/keywords section",
              'description': ''
            },
            {
              'text': 'Gamification',
              'source': 'extracted',
              'reason': "Explicitly listed in document's tags/keywords section",
              'description': ''
            }
          ],
          'summary': 'The House System is a solution designed to promote unity and inclusivity in schools by creating a gamified environment where students are assigned to houses, participate in activities, and earn rewards. The system aims to increase student motivation, peer connection, and school belongingness.',
          'document_type': 'template',
          'key_entities': [
            'Regila Marinus',
            'Nagapattinam District',
            'Tamil Nadu'
          ],
          'structured_content': {
            'Problem Statement': 'Government school environments often face challenges around student disengagement, social division (e.g., caste-based groupings), lack of identity, and exclusionary practices. Students have limited opportunities to experience belonging, team spirit, and unity, resulting in lowered motivation and participation.',
            'Theory of Change': 'Inputs: Gamification tools, house formation templates, scoreboards, teacher/HM orientation, M&E tools\nActivities: Students randomly assigned to houses, competitions and activities conducted, house leadership roles created, regular assessments\nOutputs: Formation of inclusive teams, student participation in house activities, tracking of scores and behaviors\nOutcomes: Increased student motivation, peer connection, school belongingness\nImpact: Enhanced student engagement, inclusive school culture, reduction in social exclusion',
            'Design Philosophy': 'This solution is rooted in principles of child agency, equity, and collective identity. It promotes future-readiness by fostering inclusive, joyful, and collaborative school cultures using gamification.',
            'Solution Components': 'Component: House System (4 Houses – Blue, Red, Green, Yellow)\nTools Used: Scoreboards, leadership badges, activity logs, feedback forms, House Day events\nSystem Alignment: Aligns with NEP 2020 principles of inclusion, participation, and leadership',
            'Implementation Model': 'The school is divided into 4 houses, each with diverse students and rotating leadership. Activities (academic, sports, cultural) are gamified with points and tracked via scoreboards. House Day events foster celebration and participation.\nActors: Students, Teachers, HMs, Parents\nTimeline: 1 month for onboarding; year-long implementation',
            'User Journey / Beneficiary Experience': 'Students are placed in mixed houses, take leadership, earn rewards through participation, and develop friendships beyond social barriers. They experience higher belonging, reduced fear, and pride in contributing.',
            'Evidence of Effectiveness': 'Piloted in Nagapattinam schools. Feedback from students and teachers shows improved attendance, reduced conflicts, and high participation. Early M&E data shows higher scores on belonging and school engagement.',
            'Adaptability & Reusability': 'Can be replicated in any government or private school with minimal customization. House names, reward types, and leadership rules can be adapted to context.',
            'Implementation Readiness': 'Needs orientation for teachers and HMs, printed scoreboards, and basic monitoring templates. Handbooks available in Tamil and English. House Day planning templates provided.',
            'Risks and Learnings': 'Risk: Without consistent facilitation, the system may revert to exclusion or tokenism.\nLearning: Rotating leadership and gamified scoring ensure sustained participation.',
            'Knowledge Assets Submitted': '- House System Handbook (EN & TA)\n- Scoreboard Template\n- House Day Plan\n- Pre/Post Feedback Forms\n- M&E Indicators Dashboard',
            'Partnerships and Networks': 'Implemented by Vidhya Vidhai in partnership with government schools and system leaders in Nagapattinam. Teachers, HMs, and district officials co-own the implementation.',
            'Policy or System Influence': 'Can be institutionalized through district-level circulars or incorporated into SDP planning. Aligns with government inclusivity and engagement frameworks.',
            'Contributors': 'Regila Marinus – Program Design Lead\nField Implementation Team – Vidhya Vidhai\nPilot School HMs and Teachers'
          },
          'exact_content': 'Shikshagraha - Solutions Template\n1. Basic Information\nSolution Title: House System – Design for Unity and Inclusivity in Schools\nSubmitting Organization: Vidhya Vidhai Foundation\nGeography: Nagapattinam District, Tamil Nadu\nLink- https://docs.google.com/document/d/1wv2PN8tcWyNQ4x8SxyDRQYqwwS2nqasC1PNtnZkymWs/edit?tab=t.0 \n2. Problem Statement\nGovernment school environments often face challenges around student disengagement, social division (e.g., caste-based groupings), lack of identity, and exclusionary practices. Students have limited opportunities to experience belonging, team spirit, and unity, resulting in lowered motivation and participation.\n3. Theory of Change\nInputs: Gamification tools, house formation templates, scoreboards, teacher/HM orientation, M&E tools\nActivities: Students randomly assigned to houses, competitions and activities conducted, house leadership roles created, regular assessments\nOutputs: Formation of inclusive teams, student participation in house activities, tracking of scores and behaviors\nOutcomes: Increased student motivation, peer connection, school belongingness\nImpact: Enhanced student engagement, inclusive school culture, reduction in social exclusion\n4. Design Philosophy\nThis solution is rooted in principles of child agency, equity, and collective identity. It promotes future-readiness by fostering inclusive, joyful, and collaborative school cultures using gamification.\n5. Solution Components\nComponent: House System (4 Houses – Blue, Red, Green, Yellow)\nTools Used: Scoreboards, leadership badges, activity logs, feedback forms, House Day events\nSystem Alignment: Aligns with NEP 2020 principles of inclusion, participation, and leadership\n6. Implementation Model\nThe school is divided into 4 houses, each with diverse students and rotating leadership. Activities (academic, sports, cultural) are gamified with points and tracked via scoreboards. House Day events foster celebration and participation.\nActors: Students, Teachers, HMs, Parents\nTimeline: 1 month for onboarding; year-long implementation\n7. User Journey / Beneficiary Experience\nStudents are placed in mixed houses, take leadership, earn rewards through participation, and develop friendships beyond social barriers. They experience higher belonging, reduced fear, and pride in contributing.\n8. Evidence of Effectiveness\nPiloted in Nagapattinam schools. Feedback from students and teachers shows improved attendance, reduced conflicts, and high participation. Early M&E data shows higher scores on belonging and school engagement.\n9. Adaptability & Reusability\nCan be replicated in any government or private school with minimal customization. House names, reward types, and leadership rules can be adapted to context.\n10. Implementation Readiness\nNeeds orientation for teachers and HMs, printed scoreboards, and basic monitoring templates. Handbooks available in Tamil and English. House Day planning templates provided.\n11. Risks and Learnings\nRisk: Without consistent facilitation, the system may revert to exclusion or tokenism.\nLearning: Rotating leadership and gamified scoring ensure sustained participation.\n12. Knowledge Assets Submitted\n- House System Handbook (EN & TA)\n- Scoreboard Template\n- House Day Plan\n- Pre/Post Feedback Forms\n- M&E Indicators Dashboard\n13. Partnerships and Networks\nImplemented by Vidhya Vidhai in partnership with government schools and system leaders in Nagapattinam. Teachers, HMs, and district officials co-own the implementation.\n14. Policy or System Influence\nCan be institutionalized through district-level circulars or incorporated into SDP planning. Aligns with government inclusivity and engagement frameworks.\n15. Contributors\nRegila Marinus – Program Design Lead\nField Implementation Team – Vidhya Vidhai\nPilot School HMs and Teachers\n16. Tags for Classification\n✅ Student Voice\n✅ School Environment\n✅ Inclusivity\n✅ Education Leadership\n✅ Systems Change\n✅ Gamification\n17. License & Sharing Preferences\n✅ Open Source (with attribution)',
          'url': [
            'https://docs.google.com/document/d/1wv2PN8tcWyNQ4x8SxyDRQYqwwS2nqasC1PNtnZkymWs/edit?tab=t.0'
          ],
          'subdocument': [
            {
              'title': 'Design for unity and inclusivity in schools - Nagai',
              'organization': 'Nagai',
              'tags': [
                {
                  'text': 'Inclusivity',
                  'source': 'generated',
                  'reason': 'Document focuses on strategies for promoting inclusivity in schools',
                  'description': 'Strategies and methods for creating an inclusive learning environment'
                },
                {
                  'text': 'Student Engagement',
                  'source': 'generated',
                  'reason': 'Document highlights the importance of student engagement in learning',
                  'description': 'Strategies and methods for increasing student participation and involvement in learning'
                },
                {
                  'text': 'Gamification',
                  'source': 'generated',
                  'reason': 'Document proposes the use of gamification to promote student engagement',
                  'description': 'The use of game design elements in non-game contexts to increase engagement and motivation'
                },
                {
                  'text': 'School Culture',
                  'source': 'generated',
                  'reason': 'Document aims to improve school culture by promoting inclusivity and student engagement',
                  'description': 'The social and emotional environment of a school that supports student learning and well-being'
                },
                {
                  'text': 'Education',
                  'source': 'generated',
                  'reason': 'Document is focused on educational strategies and policies',
                  'description': 'The process of teaching and learning in a school setting'
                },
                {
                  'text': 'Policy',
                  'source': 'generated',
                  'reason': 'Document proposes a policy framework for promoting inclusivity in schools',
                  'description': 'A set of rules and guidelines that govern the behavior and actions of individuals or organizations'
                },
                {
                  'text': 'Leadership',
                  'source': 'generated',
                  'reason': 'Document highlights the importance of leadership in promoting inclusivity and student engagement',
                  'description': 'The process of influencing and guiding individuals or groups towards a common goal or vision'
                },
                {
                  'text': 'Implementation',
                  'source': 'generated',
                  'reason': 'Document outlines a plan for implementing the proposed policy framework',
                  'description': 'The process of putting a plan or policy into action'
                },
                {
                  'text': 'Monitoring and Evaluation',
                  'source': 'generated',
                  'reason': 'Document proposes a plan for monitoring and evaluating the effectiveness of the policy framework',
                  'description': 'The process of tracking and assessing the progress and outcomes of a policy or program'
                }
              ],
              'summary': 'The document proposes a policy framework for promoting inclusivity and student engagement in schools through the use of gamification and other strategies. It outlines a plan for implementing the policy and monitoring its effectiveness.',
              'document_type': 'Policy',
              'key_entities': [
                'Nagai'
              ],
              'exact_content': "Design for unity and inclusivity in schools - Nagai \nWhat are the desired beliefs and behaviour shifts we wish to see in the stakeholders?\nLogical Framework: \nWhat would be the larger goal or impact of addressing this domain on inclusivity in school?\nIncreased Sense of Identity/Belongingness\nPercentage increase in students reporting a strong sense of identity and belonging within the school community through surveys or assessments.\nDecrease in feelings of isolation or alienation among students, as indicated by qualitative feedback or observation.\nImprovement in attendance rates and participation in school events or activities among students, reflecting a greater sense of connection and belonging\nIncreased Motivation & Engagement\nImprovement in student participation and involvement in classroom discussions, extracurricular activities, and academic projects.\nReduction in rates of absenteeism or disengagement, indicating higher levels of motivation and commitment among students.\nEnhanced enthusiasm for learning and academic pursuits, demonstrated through increased completion of assignments, projects, and assessments.\nEnhanced unity and inclusivity\nStrengthened relationships and connections among students from diverse backgrounds, evidenced by increased collaboration, mutual respect, and empathy.\nReduction in incidents of bullying, discrimination, or exclusion within the school community, indicating a more inclusive and supportive environment.\nIncrease in collaborative efforts and positive interactions among students from diverse backgrounds.\nImprovement in perceptions of school climate and culture related to inclusivity and acceptance.\nImproved academic performance and excellence\nReduction in achievement gaps between different student groups.\nImprovement in graduation rates and post-secondary education enrollment rates.\nIncrease in career opportunities and choices\nIntervention plan : House System \nIntroduction:\nRecognizing the importance of fostering inclusivity and student engagement in education, we propose the implementation of a School House System in Nagapattinam Government schools. This innovative approach aims to revolutionise education by integrating gamification principles to create a nurturing, empowering, and inclusive learning environment.\nCore Concepts:\nThe School House System involves dividing students into four houses - Blue, Red, Green, and Yellow - each representing a unique identity with distinct colours and symbols. Students will actively participate in a multiplayer game scenario through scores and competitions, fostering teamwork, camaraderie, and healthy competition.\nKey Objectives:\nEnhance Student Motivation & Engagement:\nUtilize gamification elements to reignite students' interest in learning and promote active participation in classroom activities.\nIncentivize school attendance and academic performance through rewards and competitions, encouraging students to strive for excellence.\nFoster a Sense of Identity & Belongingness:\nCreate a cohesive school culture by instilling pride and belongingness among students through their association with their respective house identities.\nCultivate a strong sense of community and teamwork within each house, fostering peer support and collaboration.\nPromote Unity and Inclusivity:\nRandom assignment to houses will break down social barriers and promote friendships across diverse backgrounds, fostering a culture of unity and inclusivity.\nEliminate caste-based identities within the school community, creating an equitable and inclusive environment for all students.\nImplementation:\n-House Formation: Divide students into four houses, ensuring equitable representation and diversity within each house.\n-Gamification Integration: Implement game elements such as scores, competitions, and rewards to incentivize student participation and engagement.\nleadership Development: Appoint student leaders within each house to promote peer support, collaboration, and responsible leadership.\n-Continuous Evaluation: Monitor the system's impact on academic performance, attendance, behaviour, and student well-being through regular assessments and feedback mechanisms. \nRefer: Score board\nImplementation Plan: https://docs.google.com/spreadsheets/d/1u3XXLqXT6B_8vtGSDiLPVBWeNHRi9mAwXFsRXL7BkLo/edit#gid=2089153627\nMicro Improvement Project for School Leaders (WIP): https://docs.google.com/spreadsheets/d/1u3XXLqXT6B_8vtGSDiLPVBWeNHRi9mAwXFsRXL7BkLo/edit#gid=997013997 \nHouse system plan link: https://docs.google.com/spreadsheets/d/1u3XXLqXT6B_8vtGSDiLPVBWeNHRi9mAwXFsRXL7BkLo/edit?usp=sharing\nM&E tool link: https://docs.google.com/spreadsheets/d/1kdctjtVRmhi0FqG33BH6uSVaqx3SimUwaiOpLXHtGI0/edit#gid=1448017526\nHS Tamil hand book: https://drive.google.com/file/d/1nd7hoj_QEHHh5ET5m3w8kVTQbBJzmKy2/view?usp=drive_link\nHS English hand book: https://drive.google.com/file/d/1Feg34ZTffGWjJ5WvZJY3KfS5KlIs0GWH/view?usp=drive_link\nHouse day Tamil: https://docs.google.com/document/d/1Gaq_wyB7Avb5IhAIJDnqTDfhbepZfFRYwD_vtYRCc7w/edit?usp=drive_link\nRules and guidelines for House day: https://docs.google.com/document/d/1tWHxpilLCLc9vCkFG_iqHrRNiCoCADRzT-3CgA_Io1g/edit?usp=drive_link\nPre house day (HD) form: https://docs.google.com/forms/d/1phnRUIK7KFeQ7i3V07Ahw0FvSDgMSCXSv7Seo-TMSmk/edit?usp=drive_web\nHD preparation form: https://docs.google.com/forms/d/1ZvDXQMBeX9VmvtlL_gnBNVEryMJ1DaBFm0RZERj-TkY/edit\nHD post event form: https://docs.google.com/forms/d/13O2kFyXZhEmv570LVG6GcqFgA77lYXT8GWoGkLwNISo/edit\nMonitoring and Evaluation \nM&E Indicators: \nEvaluation of the effectiveness of interventions in addressing and reducing such incidents.\nEvaluation of the effectiveness of training sessions in increasing staff knowledge and skills related to diversity and equity.\nFeedback surveys and assessments to measure the impact of training on classroom practices and school culture.\nReview and evaluation of modified lesson plans to assess their effectiveness in achieving learning objectives and promoting inclusivity.\nFeedback from students on their experiences and perceptions of classroom discussions\nFeedback from parents and teachers on the effectiveness of the associations/groups in addressing diversity-related issues.\nAssessment of the quality and effectiveness of parent-child discussions on diversity and inclusion.\nFeedback from children on their understanding and appreciation of diversity-related concepts.\nObservation of changes in children's attitudes and behaviours towards diversity and inclusion following parent-child discussions.\nDocumentation of instances where children demonstrate respect for differences and inclusive behaviours.\nEvaluation of the timeliness and appropriateness of school responses to reported incidents.\nFeedback from parents on their satisfaction with the support and resolution provided by schools.\nTracking and analysis of the utilisation of support services by affected students and families.\nAssessment of the impact of support services on addressing the effects of discrimination or bias.\nDocumentation of instances of friendship formation between students from diverse backgrounds.\nFeedback from students on the impact of peer connections on their sense of belonging and inclusion.\nObservation of student interactions and engagement levels during structured opportunities for peer connection.\nAssessment of changes in attitudes and perceptions towards diversity among participating students\nAnalysis of the Pilot schools House system implementation\nhttps://docs.google.com/spreadsheets/d/13sC-LUnYrUffR2jvSHXaw6JLGbJMfti4UM20cGZ5nJE/edit#gid=1382214911",
              'url': [
                'https://docs.google.com/spreadsheets/d/1u3XXLqXT6B_8vtGSDiLPVBWeNHRi9mAwXFsRXL7BkLo/edit#gid',
                'https://docs.google.com/spreadsheets/d/1u3XXLqXT6B_8vtGSDiLPVBWeNHRi9mAwXFsRXL7BkLo/edit?usp=sharing',
                'https://docs.google.com/spreadsheets/d/1kdctjtVRmhi0FqG33BH6uSVaqx3SimUwaiOpLXHtGI0/edit#gid',
                'https://drive.google.com/file/d/1nd7hoj_QEHHh5ET5m3w8kVTQbBJzmKy2/view?usp=drive_link',
                'https://drive.google.com/file/d/1Feg34ZTffGWjJ5WvZJY3KfS5KlIs0GWH/view?usp=drive_link',
                'https://docs.google.com/document/d/1Gaq_wyB7Avb5IhAIJDnqTDfhbepZfFRYwD_vtYRCc7w/edit?usp=drive_link',
                'https://docs.google.com/document/d/1tWHxpilLCLc9vCkFG_iqHrRNiCoCADRzT',
                'https://docs.google.com/forms/d/1phnRUIK7KFeQ7i3V07Ahw0FvSDgMSCXSv7Seo',
                'https://docs.google.com/forms/d/1ZvDXQMBeX9VmvtlL_gnBNVEryMJ1DaBFm0RZERj',
                'https://docs.google.com/forms/d/13O2kFyXZhEmv570LVG6GcqFgA77lYXT8GWoGkLwNISo/edit',
                'https://docs.google.com/spreadsheets/d/13sC'
              ],
              'subdocument': [

              ],
              'images': [

              ],
              'media_type': FileTypeChoices.DOCX
            }
          ],
          'images': [

          ]
        }
    except Exception as e:
        # log the error if needed
        print(f"[AutoTags] Error processing {file_path}: {e}")
    finally:
        # cleanup file no matter what
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as cleanup_err:
                print(f"[AutoTags] Failed to remove temp file {file_path}: {cleanup_err}")

    return extracted_data
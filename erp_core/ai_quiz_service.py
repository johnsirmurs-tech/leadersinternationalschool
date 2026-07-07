import json
import time
import logging
from typing import Optional
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from .models_syllabus import SyllabusTopic, SyllabusLearningObjective, SyllabusKnowledgeBase
from .models_quiz import QuizBank, AIGenerationJob

logger = logging.getLogger(__name__)


class CambridgeQuizGenerator:
    """
    AI-powered quiz generator trained on Cambridge syllabus content.
    Supports OpenAI GPT-4o and Google Gemini.
    """

    SYSTEM_PROMPT = """You are an expert Cambridge curriculum assessment specialist 
with deep knowledge of Cambridge Primary, Lower Secondary, IGCSE, and 
A Level syllabi. You create high-quality, pedagogically sound 
multiple-choice questions that:

1. Are precisely aligned to Cambridge learning objectives
2. Use appropriate vocabulary for the age/stage group
3. Have one clearly correct answer and three plausible distractors
4. Test genuine understanding, not just recall
5. Follow Cambridge assessment principles
6. Are free from cultural bias and ambiguity
7. Match the specified difficulty level exactly

DIFFICULTY DEFINITIONS:
- EASY: Direct recall or simple one-step application of knowledge
- MEDIUM: Multi-step reasoning or application in familiar contexts  
- HARD: Analysis, evaluation, or application in unfamiliar contexts

OUTPUT FORMAT: You must respond with valid JSON only. No other text.
"""

    QUESTION_SCHEMA = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "question_text", "option_a", "option_b",
                        "option_c", "option_d", "correct_answer",
                        "explanation", "difficulty", "cognitive_level",
                        "objective_alignment", "distractor_rationale"
                    ],
                    "properties": {
                        "question_text": {"type": "string"},
                        "option_a": {"type": "string"},
                        "option_b": {"type": "string"},
                        "option_c": {"type": "string"},
                        "option_d": {"type": "string"},
                        "correct_answer": {
                            "type": "string",
                            "enum": ["A", "B", "C", "D"]
                        },
                        "explanation": {"type": "string"},
                        "hint": {"type": "string"},
                        "difficulty": {
                            "type": "string",
                            "enum": ["EASY", "MEDIUM", "HARD"]
                        },
                        "cognitive_level": {
                            "type": "string",
                            "enum": [
                                "REMEMBER", "UNDERSTAND", "APPLY",
                                "ANALYSE", "EVALUATE", "CREATE"
                            ]
                        },
                        "objective_alignment": {"type": "string"},
                        "distractor_rationale": {
                            "type": "object",
                            "properties": {
                                "A": {"type": "string"},
                                "B": {"type": "string"},
                                "C": {"type": "string"},
                                "D": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }
    }

    def __init__(self):
        self.client = self._initialize_client()

    def _initialize_client(self):
        """Initialize the AI client based on settings."""
        ai_provider = getattr(settings, 'AI_QUIZ_PROVIDER', 'openai')
        if ai_provider == 'openai':
            try:
                from openai import OpenAI
                api_key = getattr(settings, 'OPENAI_API_KEY', 'dummy-key')
                return OpenAI(api_key=api_key)
            except ImportError:
                # Return None, we will mock for testing if openai is missing
                return None
        elif ai_provider == 'google':
            try:
                import google.generativeai as genai
                api_key = getattr(settings, 'GOOGLE_AI_API_KEY', 'dummy-key')
                genai.configure(api_key=api_key)
                return genai.GenerativeModel('gemini-1.5-pro')
            except ImportError:
                return None
        return None

    def build_generation_prompt(
        self,
        subject_name: str,
        stage_name: str,
        stage_type: str,
        topics: list,
        difficulty: str,
        num_questions: int,
        cognitive_levels: list,
        knowledge_base_content: str,
        learning_objectives: list,
        age_range: str = "",
    ) -> str:
        """Build a comprehensive, context-rich prompt for question generation."""
        if difficulty == 'MIXED':
            easy_count = num_questions // 3
            hard_count = num_questions // 3
            medium_count = num_questions - easy_count - hard_count
            difficulty_instruction = (
                f"Generate a MIX of difficulties:\n"
                f"- {easy_count} EASY questions\n"
                f"- {medium_count} MEDIUM questions\n"
                f"- {hard_count} HARD questions"
            )
        else:
            difficulty_instruction = (
                f"ALL questions must be {difficulty} difficulty"
            )

        cognitive_str = (
            ", ".join(cognitive_levels)
            if cognitive_levels
            else "REMEMBER, UNDERSTAND, APPLY"
        )

        topics_str = "\n".join([
            f"- {t['title']}: {t['description']}"
            for t in topics
        ])

        objectives_str = "\n".join([
            f"• {obj}" for obj in learning_objectives[:20]
        ])

        prompt = f"""
CAMBRIDGE CURRICULUM QUIZ GENERATION REQUEST
============================================

SUBJECT: {subject_name}
CAMBRIDGE STAGE: {stage_name} ({stage_type})
AGE GROUP: {age_range}

TOPICS TO COVER:
{topics_str}

CAMBRIDGE LEARNING OBJECTIVES TO ASSESS:
{objectives_str}

DIFFICULTY: {difficulty_instruction}

COGNITIVE LEVELS TO INCLUDE: {cognitive_str}
(Bloom's Taxonomy levels - distribute appropriately)

SYLLABUS CONTENT KNOWLEDGE BASE:
{knowledge_base_content}

GENERATION REQUIREMENTS:
========================
Generate exactly {num_questions} multiple-choice questions.

Each question MUST:
1. Directly assess one or more of the listed Cambridge learning objectives
2. Have exactly 4 options (A, B, C, D)
3. Have ONLY ONE correct answer
4. Have 3 carefully crafted distractors based on common misconceptions
5. Include a clear, educational explanation of why the correct answer is right
6. Include why each wrong answer is wrong (distractor_rationale)
7. Use language appropriate for {age_range} students
8. Include a helpful hint (not giving away the answer)
9. Specify which learning objective it targets (objective_alignment)
10. Avoid trick questions or ambiguous wording

Return ONLY valid JSON matching this structure:
{{
    "questions": [
        {{
            "question_text": "The complete question text here?",
            "option_a": "First option",
            "option_b": "Second option", 
            "option_c": "Third option",
            "option_d": "Fourth option",
            "correct_answer": "A",
            "explanation": "Detailed explanation of why A is correct...",
            "hint": "Think about...",
            "difficulty": "EASY",
            "cognitive_level": "UNDERSTAND",
            "objective_alignment": "Students should be able to...",
            "distractor_rationale": {{
                "B": "This is wrong because...",
                "C": "This is wrong because...",
                "D": "This is wrong because..."
            }}
        }}
    ]
}}
"""
        return prompt.strip()

    def generate_questions(self, job) -> list:
        """Main generation method."""
        start_time = time.time()
        topics = job.topics.all()

        kb_content = self._gather_knowledge_base(topics)

        objectives = SyllabusLearningObjective.objects.filter(
            topic__in=topics,
            is_active=True
        ).values_list('statement', flat=True)[:30]

        topics_data = [
            {
                'title': t.title,
                'description': t.description or t.learning_objectives[:200]
            }
            for t in topics
        ]

        prompt = self.build_generation_prompt(
            subject_name=job.subject.name,
            stage_name=job.stage.name,
            stage_type=job.stage.get_stage_type_display(),
            topics=topics_data,
            difficulty=job.difficulty,
            num_questions=job.num_questions_requested,
            cognitive_levels=job.cognitive_levels,
            knowledge_base_content=kb_content,
            learning_objectives=list(objectives),
            age_range=job.stage.age_range,
        )

        try:
            questions_data = self._call_ai_api(prompt, job)
        except Exception as e:
            job.status = 'FAILED'
            job.error_message = str(e)
            job.save()
            raise

        elapsed = time.time() - start_time
        job.generation_time_seconds = elapsed
        return questions_data

    def _gather_knowledge_base(self, topics) -> str:
        kb_items = SyllabusKnowledgeBase.objects.filter(
            topic__in=topics
        ).order_by('topic', 'content_type')

        if not kb_items.exists():
            content_parts = []
            for topic in topics:
                content_parts.append(
                    f"\n=== {topic.title} ===\n"
                    f"{topic.description}\n"
                    f"Learning Objectives:\n"
                    f"{topic.learning_objectives}\n"
                    f"Key Vocabulary: {topic.key_vocabulary}"
                )
            return "\n".join(content_parts)

        content_parts = []
        current_topic = None

        for item in kb_items:
            if item.topic != current_topic:
                current_topic = item.topic
                content_parts.append(f"\n=== TOPIC: {item.topic.title} ===")
                content_parts.append(
                    f"Key Vocabulary: {item.topic.key_vocabulary}"
                )

            content_parts.append(
                f"\n[{item.get_content_type_display()}] {item.title}:\n"
                f"{item.content}"
            )

        full_content = "\n".join(content_parts)
        if len(full_content) > 8000:
            full_content = full_content[:8000] + "\n...[content truncated]"

        return full_content

    def _call_ai_api(self, prompt: str, job) -> list:
        # If client is None (development / sandbox / testing without API keys), we generate sandbox questions
        if self.client is None:
            return self._generate_sandbox_questions(job)

        ai_provider = getattr(settings, 'AI_QUIZ_PROVIDER', 'openai')
        model = getattr(settings, 'AI_QUIZ_MODEL', 'gpt-4o')

        if ai_provider == 'openai':
            return self._call_openai(prompt, job, model)
        elif ai_provider == 'google':
            return self._call_gemini(prompt, job)
        return self._generate_sandbox_questions(job)

    def _call_openai(self, prompt: str, job, model: str) -> list:
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=4000,
        )

        job.prompt_tokens_used = response.usage.prompt_tokens
        job.completion_tokens_used = response.usage.completion_tokens
        job.ai_model = model
        job.save(update_fields=[
            'prompt_tokens_used',
            'completion_tokens_used',
            'ai_model'
        ])

        content = response.choices[0].message.content
        data = json.loads(content)
        return data.get('questions', [])

    def _call_gemini(self, prompt: str, job) -> list:
        full_prompt = f"{self.SYSTEM_PROMPT}\n\n{prompt}"
        response = self.client.generate_content(
            full_prompt,
            generation_config={
                'temperature': 0.7,
                'response_mime_type': 'application/json',
            }
        )
        job.ai_model = 'gemini-1.5-pro'
        job.save(update_fields=['ai_model'])

        data = json.loads(response.text)
        return data.get('questions', [])

    def _generate_sandbox_questions(self, job) -> list:
        """Create mock sandbox questions when API key is missing or for local testing."""
        job.ai_model = 'sandbox-mock-generator'
        job.save(update_fields=['ai_model'])
        
        questions = []
        for i in range(job.num_questions_requested):
            questions.append({
                "question_text": f"Sandbox Question {i+1}: What is the primary characteristic of {job.subject.name} for {job.stage.name}?",
                "option_a": "Correct Sandbox Answer Option",
                "option_b": "Incorrect Sandbox Distractor B",
                "option_c": "Incorrect Sandbox Distractor C",
                "option_d": "Incorrect Sandbox Distractor D",
                "correct_answer": "A",
                "explanation": "Option A is correct because this is a mock sandbox generated question.",
                "hint": "Try Option A.",
                "difficulty": job.difficulty if job.difficulty != 'MIXED' else 'MEDIUM',
                "cognitive_level": "UNDERSTAND",
                "objective_alignment": "Mock Objective Alignment Statement",
                "distractor_rationale": {
                    "B": "Distractor B rationale explanation.",
                    "C": "Distractor C rationale explanation.",
                    "D": "Distractor D rationale explanation."
                }
            })
        return questions

    def save_generated_questions(self, questions_data: list, job) -> list:
        saved_questions = []
        topics = list(job.topics.all())
        primary_topic = topics[0] if topics else None

        for i, q_data in enumerate(questions_data):
            try:
                required = [
                    'question_text', 'option_a', 'option_b',
                    'option_c', 'option_d', 'correct_answer',
                    'explanation'
                ]
                if not all(q_data.get(f) for f in required):
                    continue

                correct = q_data.get('correct_answer', '').upper()
                if correct not in ['A', 'B', 'C', 'D']:
                    continue

                question = QuizBank.objects.create(
                    topic=primary_topic,
                    stage=job.stage,
                    subject=job.subject,
                    difficulty=q_data.get('difficulty', job.difficulty),
                    cognitive_level=q_data.get('cognitive_level', 'UNDERSTAND'),
                    question_text=q_data['question_text'],
                    option_a=q_data['option_a'],
                    option_b=q_data['option_b'],
                    option_c=q_data['option_c'],
                    option_d=q_data['option_d'],
                    correct_answer=correct,
                    explanation=q_data.get('explanation', ''),
                    hint=q_data.get('hint', ''),
                    distractor_rationale=q_data.get('distractor_rationale', {}),
                    ai_model_used=job.ai_model,
                    ai_generation_prompt=f"Job: {job.id}",
                    status='AI_GENERATED',
                    created_by=job.requested_by,
                )
                saved_questions.append(question)
                job.generated_questions.add(question)
            except Exception as e:
                logger.error(f"Error saving generated question: {e}")
                continue

        job.num_questions_generated = len(saved_questions)
        job.status = 'COMPLETED' if len(saved_questions) >= job.num_questions_requested * 0.8 else 'PARTIAL'
        job.completed_at = timezone.now()
        job.save()
        return saved_questions


class QuizGenerationOrchestrator:
    """Orchestrates quiz generation."""

    @staticmethod
    def initiate_generation(
        user,
        subject_id: int,
        stage_id: int,
        topic_ids: list,
        difficulty: str,
        num_questions: int,
        cognitive_levels: list = None,
        unit_id: int = None,
    ) -> dict:
        from .models_syllabus import CambridgeSubject, CambridgeStage, SyllabusTopic, SyllabusUnit

        if not topic_ids:
            raise ValueError("At least one topic must be selected")

        if num_questions < 1 or num_questions > 50:
            raise ValueError("Number of questions must be between 1 and 50")

        if difficulty not in ['EASY', 'MEDIUM', 'HARD', 'MIXED']:
            raise ValueError(f"Invalid difficulty: {difficulty}")

        subject = CambridgeSubject.objects.get(id=subject_id)
        stage = CambridgeStage.objects.get(id=stage_id)
        topics = SyllabusTopic.objects.filter(id__in=topic_ids, is_active=True)

        if not topics.exists():
            raise ValueError("No valid topics found")

        job = AIGenerationJob.objects.create(
            subject=subject,
            stage=stage,
            unit=SyllabusUnit.objects.filter(id=unit_id).first() if unit_id else None,
            difficulty=difficulty,
            num_questions_requested=num_questions,
            cognitive_levels=cognitive_levels or ['REMEMBER', 'UNDERSTAND', 'APPLY'],
            status='PROCESSING',
            requested_by=user,
        )
        job.topics.set(topics)
        job.save()

        try:
            generator = CambridgeQuizGenerator()
            questions_data = generator.generate_questions(job)
            saved_questions = generator.save_generated_questions(questions_data, job)

            return {
                'success': True,
                'job_id': str(job.id),
                'questions_generated': len(saved_questions),
                'questions': saved_questions,
                'job': job,
            }
        except Exception as e:
            job.status = 'FAILED'
            job.error_message = str(e)
            job.save()
            logger.error(f"AI generation failed for job {job.id}: {e}")
            raise

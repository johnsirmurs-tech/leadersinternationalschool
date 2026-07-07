from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid
import json

from .models_syllabus import (
    CambridgeStage, CambridgeSubject, SyllabusUnit,
    SyllabusTopic, SyllabusLearningObjective
)


class QuizBank(models.Model):
    """
    Repository of AI-generated and teacher-approved questions.
    Questions are stored here and reused across quizzes.
    """
    DIFFICULTY_LEVELS = [
        ('EASY', 'Easy'),
        ('MEDIUM', 'Medium'),
        ('HARD', 'Hard'),
        ('MIXED', 'Mixed'),
    ]

    QUESTION_STATUS = [
        ('AI_GENERATED', 'AI Generated - Pending Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('EDITED', 'Edited & Approved'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.ForeignKey(
        SyllabusTopic, on_delete=models.CASCADE,
        related_name='question_bank'
    )
    objective = models.ForeignKey(
        SyllabusLearningObjective, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='questions'
    )
    stage = models.ForeignKey(
        CambridgeStage, on_delete=models.CASCADE,
        related_name='questions'
    )
    subject = models.ForeignKey(
        CambridgeSubject, on_delete=models.CASCADE,
        related_name='questions'
    )
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_LEVELS)
    cognitive_level = models.CharField(
        max_length=20,
        choices=SyllabusLearningObjective.COGNITIVE_LEVELS,
        default='UNDERSTAND'
    )
    # The question content
    question_text = models.TextField()
    question_html = models.TextField(
        blank=True,
        help_text="HTML formatted version of the question"
    )
    # Image support
    question_image = models.ImageField(
        upload_to='quiz/questions/', blank=True, null=True
    )
    # Answer options
    option_a = models.TextField()
    option_b = models.TextField()
    option_c = models.TextField()
    option_d = models.TextField()
    # Can have optional 5th option
    option_e = models.TextField(blank=True)
    # Correct answer
    correct_answer = models.CharField(
        max_length=1,
        choices=[
            ('A', 'A'), ('B', 'B'), ('C', 'C'),
            ('D', 'D'), ('E', 'E')
        ]
    )
    # Explanation for learning
    explanation = models.TextField(
        help_text="Why this answer is correct - shown after submission"
    )
    hint = models.TextField(
        blank=True,
        help_text="Optional hint shown if student requests help"
    )
    # Distractor rationale (why wrong answers are wrong)
    distractor_rationale = models.JSONField(
        default=dict,
        help_text="{'A': 'why A is wrong', 'B': 'why B is wrong', ...}"
    )
    # AI metadata
    ai_model_used = models.CharField(max_length=50, blank=True)
    ai_generation_prompt = models.TextField(blank=True)
    ai_confidence_score = models.FloatField(
        null=True, blank=True,
        help_text="AI's confidence in question quality (0-1)"
    )
    # Review
    status = models.CharField(
        max_length=20,
        choices=QUESTION_STATUS,
        default='AI_GENERATED'
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_questions'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    # Usage statistics
    times_used = models.IntegerField(default=0)
    times_correct = models.IntegerField(default=0)
    times_incorrect = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True,
        related_name='created_questions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['topic', 'difficulty', 'status']),
            models.Index(fields=['subject', 'stage', 'difficulty']),
        ]

    def __str__(self):
        return f"[{self.difficulty}] {self.question_text[:80]}"

    @property
    def success_rate(self):
        total = self.times_correct + self.times_incorrect
        if total == 0:
            return None
        return round((self.times_correct / total) * 100, 1)

    def get_options(self):
        options = {
            'A': self.option_a,
            'B': self.option_b,
            'C': self.option_c,
            'D': self.option_d,
        }
        if self.option_e:
            options['E'] = self.option_e
        return options

    def is_answer_correct(self, answer):
        return answer.upper() == self.correct_answer.upper()


class Quiz(models.Model):
    """
    A quiz assigned to students.
    Teacher creates → Students complete → Auto-graded.
    """
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('ACTIVE', 'Active'),
        ('CLOSED', 'Closed'),
        ('ARCHIVED', 'Archived'),
    ]

    ASSIGNMENT_TYPES = [
        ('CLASS', 'Whole Class'),
        ('GROUP', 'Student Group'),
        ('INDIVIDUAL', 'Individual Students'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    # Curriculum alignment
    subject = models.ForeignKey(
        CambridgeSubject, on_delete=models.CASCADE,
        related_name='quizzes'
    )
    stage = models.ForeignKey(
        CambridgeStage, on_delete=models.CASCADE,
        related_name='quizzes'
    )
    unit = models.ForeignKey(
        SyllabusUnit, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='quizzes'
    )
    topics = models.ManyToManyField(
        SyllabusTopic,
        related_name='quizzes'
    )
    # Questions
    questions = models.ManyToManyField(
        QuizBank,
        through='QuizQuestion',
        related_name='quizzes'
    )
    total_questions = models.IntegerField(default=0)
    # Settings
    difficulty = models.CharField(
        max_length=10,
        choices=QuizBank.DIFFICULTY_LEVELS,
        default='MIXED'
    )
    time_limit_minutes = models.IntegerField(
        null=True, blank=True,
        help_text="Leave blank for no time limit"
    )
    allow_retakes = models.BooleanField(default=False)
    max_retakes = models.IntegerField(default=1)
    show_answers_after = models.BooleanField(
        default=True,
        help_text="Show correct answers after submission"
    )
    show_explanations = models.BooleanField(default=True)
    randomize_questions = models.BooleanField(default=True)
    randomize_options = models.BooleanField(default=False)
    passing_score = models.IntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Passing percentage"
    )
    # Assignment
    assignment_type = models.CharField(
        max_length=20,
        choices=ASSIGNMENT_TYPES,
        default='CLASS'
    )
    assigned_class = models.ForeignKey(
        'erp_core.Class', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='quizzes'
    )
    assigned_students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='assigned_quizzes'
    )
    # Scheduling
    available_from = models.DateTimeField(default=timezone.now)
    available_until = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='DRAFT'
    )
    # AI generation metadata
    ai_generated = models.BooleanField(default=False)
    ai_generation_params = models.JSONField(
        default=dict,
        help_text="Parameters used for AI generation"
    )
    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='created_quizzes'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Quizzes'

    def __str__(self):
        return f"{self.title} ({self.subject.name} - {self.stage.name})"

    def publish(self, user):
        """Publish quiz to make it available to students."""
        self.status = 'PUBLISHED'
        self.published_at = timezone.now()
        self.save()

    @property
    def is_available(self):
        now = timezone.now()
        if self.status != 'PUBLISHED':
            return False
        if self.available_from and now < self.available_from:
            return False
        if self.available_until and now > self.available_until:
            return False
        return True

    def get_student_attempt(self, student):
        return self.attempts.filter(
            student=student
        ).order_by('-started_at').first()

    def get_completion_rate(self):
        if self.assignment_type == 'CLASS' and self.assigned_class:
            total = self.assigned_class.students.count()
        else:
            total = self.assigned_students.count()
        if total == 0:
            return 0
        completed = self.attempts.filter(
            status='COMPLETED'
        ).values('student').distinct().count()
        return round((completed / total) * 100, 1)


class QuizQuestion(models.Model):
    """Through model for Quiz-Question with ordering."""
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name='quiz_questions'
    )
    question = models.ForeignKey(
        QuizBank, on_delete=models.CASCADE,
        related_name='quiz_inclusions'
    )
    order = models.IntegerField(default=0)
    marks = models.IntegerField(default=1)

    class Meta:
        ordering = ['order']
        unique_together = ['quiz', 'question']


class QuizAttempt(models.Model):
    """
    Student's attempt at a quiz.
    Tracks start, answers, and completion.
    """
    STATUS_CHOICES = [
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('TIMED_OUT', 'Timed Out'),
        ('ABANDONED', 'Abandoned'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name='attempts'
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='quiz_attempts'
    )
    attempt_number = models.IntegerField(default=1)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='IN_PROGRESS'
    )
    # Question order for this attempt (for randomization)
    question_order = models.JSONField(
        default=list,
        help_text="List of question UUIDs in the order presented"
    )
    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_taken_seconds = models.IntegerField(null=True, blank=True)
    # Scores
    total_marks = models.IntegerField(default=0)
    marks_obtained = models.IntegerField(default=0)
    percentage_score = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)
    # Per-difficulty breakdown
    score_breakdown = models.JSONField(
        default=dict,
        help_text="{'EASY': {'correct': 3, 'total': 5}, ...}"
    )

    class Meta:
        ordering = ['-started_at']
        unique_together = ['quiz', 'student', 'attempt_number']

    def __str__(self):
        return (
            f"{self.student.get_full_name()} - "
            f"{self.quiz.title} - Attempt {self.attempt_number}"
        )

    def calculate_score(self):
        """Calculate and save final score."""
        answers = self.answers.all()
        total_marks = sum(
            a.quiz_question.marks for a in answers
        )
        marks_obtained = sum(
            a.quiz_question.marks
            for a in answers if a.is_correct
        )
        self.total_marks = total_marks
        self.marks_obtained = marks_obtained
        self.percentage_score = (
            (marks_obtained / total_marks * 100)
            if total_marks > 0 else 0
        )
        self.passed = (
            self.percentage_score >= self.quiz.passing_score
        )

        # Breakdown by difficulty
        breakdown = {}
        for answer in answers:
            diff = answer.question.difficulty
            if diff not in breakdown:
                breakdown[diff] = {'correct': 0, 'total': 0}
            breakdown[diff]['total'] += 1
            if answer.is_correct:
                breakdown[diff]['correct'] += 1
        self.score_breakdown = breakdown

        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        self.time_taken_seconds = int(
            (self.completed_at - self.started_at).total_seconds()
        )
        self.save()

        # Update question bank statistics
        for answer in answers:
            q = answer.question
            q.times_used += 1
            if answer.is_correct:
                q.times_correct += 1
            else:
                q.times_incorrect += 1
            q.save(update_fields=[
                'times_used', 'times_correct', 'times_incorrect'
            ])

        return self.percentage_score


class StudentAnswer(models.Model):
    """Individual answer to a question in an attempt."""
    attempt = models.ForeignKey(
        QuizAttempt, on_delete=models.CASCADE,
        related_name='answers'
    )
    quiz_question = models.ForeignKey(
        QuizQuestion, on_delete=models.CASCADE
    )
    question = models.ForeignKey(
        QuizBank, on_delete=models.CASCADE
    )
    selected_option = models.CharField(
        max_length=1,
        choices=[
            ('A', 'A'), ('B', 'B'), ('C', 'C'),
            ('D', 'D'), ('E', 'E')
        ],
        null=True, blank=True
    )
    is_correct = models.BooleanField(default=False)
    time_spent_seconds = models.IntegerField(default=0)
    answered_at = models.DateTimeField(auto_now_add=True)
    # Flag for review
    flagged_for_review = models.BooleanField(default=False)

    class Meta:
        unique_together = ['attempt', 'quiz_question']

    def save(self, *args, **kwargs):
        if self.selected_option:
            self.is_correct = self.question.is_answer_correct(
                self.selected_option
            )
        super().save(*args, **kwargs)


class AIGenerationJob(models.Model):
    """
    Track AI quiz generation jobs.
    Each click of "Generate" creates one job.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('PARTIAL', 'Partially Completed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # What to generate
    subject = models.ForeignKey(
        CambridgeSubject, on_delete=models.CASCADE
    )
    stage = models.ForeignKey(CambridgeStage, on_delete=models.CASCADE)
    unit = models.ForeignKey(
        SyllabusUnit, on_delete=models.SET_NULL,
        null=True, blank=True
    )
    topics = models.ManyToManyField(SyllabusTopic)
    difficulty = models.CharField(max_length=10)
    num_questions_requested = models.IntegerField()
    num_questions_generated = models.IntegerField(default=0)
    cognitive_levels = models.JSONField(
        default=list,
        help_text="List of cognitive levels to include"
    )
    # Status
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='PENDING'
    )
    error_message = models.TextField(blank=True)
    # AI details
    ai_model = models.CharField(max_length=50, default='gpt-4o')
    prompt_tokens_used = models.IntegerField(default=0)
    completion_tokens_used = models.IntegerField(default=0)
    generation_time_seconds = models.FloatField(null=True, blank=True)
    # Generated questions
    generated_questions = models.ManyToManyField(
        QuizBank,
        blank=True,
        related_name='generation_jobs'
    )
    # Audit
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='ai_generation_jobs'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return (
            f"AI Gen {self.id} - "
            f"{self.subject.name}/{self.stage.name} - "
            f"{self.num_questions_requested}Q"
        )

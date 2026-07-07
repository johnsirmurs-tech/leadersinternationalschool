from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid


class CambridgeStage(models.Model):
    """
    Cambridge curriculum stages.
    Primary (1-6), Lower Secondary (7-9), IGCSE (10-11), AS/A Level (12-13)
    """
    STAGE_TYPES = [
        ('PRIMARY', 'Cambridge Primary (Stages 1-6)'),
        ('LOWER_SEC', 'Cambridge Lower Secondary (Stages 7-9)'),
        ('IGCSE', 'Cambridge IGCSE (Grades 10-11)'),
        ('AS_LEVEL', 'Cambridge AS Level (Grade 12)'),
        ('A_LEVEL', 'Cambridge A Level (Grade 13)'),
        ('EARLY_YEARS', 'Early Years (Pre-Primary)'),
    ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    stage_type = models.CharField(max_length=20, choices=STAGE_TYPES)
    stage_number = models.IntegerField(
        null=True, blank=True,
        help_text="Stage number (1-6 for Primary, 7-9 for Lower Sec, etc.)"
    )
    age_range = models.CharField(
        max_length=20, blank=True,
        help_text="e.g., 5-6 years"
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['stage_type', 'stage_number']

    def __str__(self):
        return f"{self.code} - {self.name}"


class CambridgeSubject(models.Model):
    """Cambridge subjects with their syllabi."""
    SUBJECT_GROUPS = [
        ('LANGUAGES', 'Languages'),
        ('MATHEMATICS', 'Mathematics'),
        ('SCIENCES', 'Sciences'),
        ('HUMANITIES', 'Humanities & Social Sciences'),
        ('ARTS', 'Arts & Technology'),
        ('ICT', 'ICT & Computing'),
    ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    subject_group = models.CharField(max_length=20, choices=SUBJECT_GROUPS)
    stages = models.ManyToManyField(
        CambridgeStage,
        through='SubjectSyllabusMap',
        related_name='subjects'
    )
    description = models.TextField(blank=True)
    syllabus_code = models.CharField(
        max_length=20, blank=True,
        help_text="Official Cambridge syllabus code e.g., 0580 (Maths)"
    )
    is_active = models.BooleanField(default=True)
    icon = models.CharField(max_length=50, blank=True, default='bi-book')
    color = models.CharField(max_length=20, blank=True, default='primary')

    class Meta:
        ordering = ['subject_group', 'name']

    def __str__(self):
        return f"{self.code} - {self.name}"


class SubjectSyllabusMap(models.Model):
    """Maps subjects to stages with specific syllabus content."""
    subject = models.ForeignKey(CambridgeSubject, on_delete=models.CASCADE)
    stage = models.ForeignKey(CambridgeStage, on_delete=models.CASCADE)
    syllabus_year = models.CharField(
        max_length=10, default='2024',
        help_text="e.g., 2024, 2024-2026"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['subject', 'stage']


class SyllabusUnit(models.Model):
    """
    Top-level units/strands within a subject and stage.
    e.g., Cambridge Primary Mathematics Stage 3 - Unit 1: Numbers
    """
    subject = models.ForeignKey(
        CambridgeSubject, on_delete=models.CASCADE,
        related_name='units'
    )
    stage = models.ForeignKey(
        CambridgeStage, on_delete=models.CASCADE,
        related_name='units'
    )
    unit_number = models.IntegerField()
    code = models.CharField(max_length=30, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    learning_hours = models.IntegerField(
        default=0,
        help_text="Recommended teaching hours"
    )
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['stage', 'subject', 'unit_number']
        unique_together = ['subject', 'stage', 'unit_number']

    def __str__(self):
        return f"{self.code}: {self.title}"


class SyllabusTopic(models.Model):
    """
    Topics within a unit.
    e.g., "Fractions", "Decimals", "Percentages" within Numbers unit.
    """
    unit = models.ForeignKey(
        SyllabusUnit, on_delete=models.CASCADE,
        related_name='topics'
    )
    topic_number = models.CharField(max_length=10)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # Cambridge learning objectives
    learning_objectives = models.TextField(
        help_text="Comma or newline separated Cambridge learning objectives"
    )
    key_vocabulary = models.TextField(
        blank=True,
        help_text="Key terms and vocabulary for this topic"
    )
    prior_knowledge = models.TextField(
        blank=True,
        help_text="What students should know before this topic"
    )
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['unit', 'order', 'topic_number']

    def __str__(self):
        return f"{self.unit.code}.{self.topic_number}: {self.title}"

    @property
    def objectives_list(self):
        return [
            obj.strip()
            for obj in self.learning_objectives.replace('\r', '').split('\n')
            if obj.strip()
        ]


class SyllabusLearningObjective(models.Model):
    """
    Individual learning objectives from Cambridge syllabus.
    These are the atomic units used for AI quiz generation.
    """
    COGNITIVE_LEVELS = [
        ('REMEMBER', 'Remember (Knowledge)'),
        ('UNDERSTAND', 'Understand (Comprehension)'),
        ('APPLY', 'Apply (Application)'),
        ('ANALYSE', 'Analyse (Analysis)'),
        ('EVALUATE', 'Evaluate (Evaluation)'),
        ('CREATE', 'Create (Synthesis)'),
    ]

    topic = models.ForeignKey(
        SyllabusTopic, on_delete=models.CASCADE,
        related_name='objectives'
    )
    code = models.CharField(max_length=30, unique=True)
    statement = models.TextField(
        help_text="The exact Cambridge learning objective statement"
    )
    cognitive_level = models.CharField(
        max_length=20, choices=COGNITIVE_LEVELS,
        default='UNDERSTAND'
    )
    # AI training context
    context_notes = models.TextField(
        blank=True,
        help_text="Additional context for AI question generation"
    )
    example_questions = models.TextField(
        blank=True,
        help_text="Sample questions for this objective (used in AI training)"
    )
    common_misconceptions = models.TextField(
        blank=True,
        help_text="Common student errors/misconceptions (for distractor generation)"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['topic', 'code']

    def __str__(self):
        return f"{self.code}: {self.statement[:80]}"


class SyllabusKnowledgeBase(models.Model):
    """
    Rich content knowledge base for each topic.
    This is what the AI uses to generate accurate, syllabus-aligned questions.
    """
    CONTENT_TYPES = [
        ('CONCEPT', 'Core Concept Explanation'),
        ('WORKED_EXAMPLE', 'Worked Example'),
        ('FORMULA', 'Formula / Rule'),
        ('DEFINITION', 'Definition'),
        ('FACT', 'Key Fact'),
        ('PROCESS', 'Process / Method'),
        ('COMPARISON', 'Comparison / Contrast'),
        ('CASE_STUDY', 'Case Study'),
    ]

    topic = models.ForeignKey(
        SyllabusTopic, on_delete=models.CASCADE,
        related_name='knowledge_base'
    )
    objective = models.ForeignKey(
        SyllabusLearningObjective, on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='knowledge_items'
    )
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPES)
    title = models.CharField(max_length=200)
    content = models.TextField(
        help_text="The actual syllabus content, explanations, examples"
    )
    # Structured data for AI
    difficulty_easy = models.TextField(
        blank=True,
        help_text="Easy-level question angles for this content"
    )
    difficulty_medium = models.TextField(
        blank=True,
        help_text="Medium-level question angles for this content"
    )
    difficulty_hard = models.TextField(
        blank=True,
        help_text="Hard-level question angles for this content"
    )
    tags = models.CharField(
        max_length=500, blank=True,
        help_text="Comma-separated tags for content retrieval"
    )
    source = models.CharField(
        max_length=200, blank=True,
        help_text="Source reference (Cambridge textbook, syllabus document)"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['topic', 'content_type']

    def __str__(self):
        return f"{self.topic}: {self.title}"

    def get_ai_context(self):
        """Format content for AI prompt injection."""
        context = f"Topic: {self.topic.title}\n"
        context += f"Content Type: {self.get_content_type_display()}\n"
        context += f"Title: {self.title}\n"
        context += f"Content:\n{self.content}\n"
        if self.topic.key_vocabulary:
            context += f"Key Vocabulary: {self.topic.key_vocabulary}\n"
        return context

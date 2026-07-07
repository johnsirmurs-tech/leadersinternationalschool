from django.db import models
from django.conf import settings
from pgvector.django import VectorField, HnswIndex
import numpy as np


class SyllabusEmbedding(models.Model):
    """
    Stores vector embeddings for syllabus content.
    Lives in PostgreSQL alongside all other data.
    """

    CONTENT_TYPES = [
        ('TOPIC', 'Syllabus Topic'),
        ('OBJECTIVE', 'Learning Objective'),
        ('KNOWLEDGE', 'Knowledge Base Item'),
        ('EXAMPLE', 'Worked Example'),
        ('PAST_QUESTION', 'Past Exam Question'),
        ('DEFINITION', 'Definition'),
    ]

    content_type = models.CharField(max_length=20, choices=CONTENT_TYPES)
    content_text = models.TextField(
        help_text="The raw text that was converted to an embedding"
    )
    # We use a default dimension of 384 for sentence-transformers local model, or 1536 for OpenAI small.
    # We retrieve this dynamically from settings, but VectorField needs a dimension argument in the field definition.
    # Since model fields must specify dimensions, we read from settings or default to 384.
    # Note: django-pgvector/pgvector.django VectorField dimensions can be set to settings.EMBEDDING_DIMENSIONS.
    # But since django migrations require serializability, we can set dimensions=384. Let's use 384 (MiniLM standard).
    embedding = VectorField(dimensions=384)

    subject = models.CharField(max_length=100, db_index=True)
    stage = models.CharField(max_length=100, db_index=True)
    stage_type = models.CharField(max_length=20, db_index=True)
    unit_title = models.CharField(max_length=200, blank=True)
    topic_title = models.CharField(max_length=200, blank=True)
    section_title = models.CharField(max_length=200, blank=True)
    difficulty = models.CharField(max_length=10, blank=True)
    cognitive_level = models.CharField(max_length=20, blank=True)

    topic = models.ForeignKey(
        'SyllabusTopic',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='embeddings'
    )
    objective = models.ForeignKey(
        'SyllabusLearningObjective',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='embeddings'
    )
    knowledge_item = models.ForeignKey(
        'SyllabusKnowledgeBase',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='embeddings'
    )

    embedding_model = models.CharField(
        max_length=100,
        default='all-MiniLM-L6-v2',
        help_text="Model used to generate this embedding"
    )
    embedding_dimensions = models.IntegerField(default=384)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            HnswIndex(
                name='syllabus_embedding_hnsw_idx',
                fields=['embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops']
            ),
            models.Index(
                fields=['content_type', 'subject', 'stage_type'],
                name='embedding_filter_idx'
            ),
            models.Index(
                fields=['topic'],
                name='embedding_topic_idx'
            ),
        ]
        verbose_name = "Syllabus Embedding"
        verbose_name_plural = "Syllabus Embeddings"

    def __str__(self):
        return (
            f"[{self.content_type}] {self.subject} - "
            f"{self.topic_title[:50]}"
        )

    @classmethod
    def cosine_search(
        cls,
        query_embedding: list,
        subject: str = None,
        stage_type: str = None,
        content_types: list = None,
        limit: int = 5,
        min_similarity: float = 0.3,
    ):
        from pgvector.django import CosineDistance

        qs = cls.objects.all()

        if subject:
            qs = qs.filter(subject__iexact=subject)
        if stage_type:
            qs = qs.filter(stage_type=stage_type)
        if content_types:
            qs = qs.filter(content_type__in=content_types)

        max_distance = 1 - min_similarity

        results = (
            qs
            .annotate(
                distance=CosineDistance('embedding', query_embedding)
            )
            .filter(distance__lte=max_distance)
            .order_by('distance')
            [:limit]
        )

        return results

    @classmethod
    def find_similar_questions(
        cls,
        query_embedding: list,
        subject: str,
        stage_type: str,
        limit: int = 10,
    ):
        return cls.cosine_search(
            query_embedding=query_embedding,
            subject=subject,
            stage_type=stage_type,
            content_types=['PAST_QUESTION', 'EXAMPLE'],
            limit=limit,
            min_similarity=0.4,
        )

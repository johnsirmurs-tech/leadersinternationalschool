import os
import logging
from django.db import models

logger = logging.getLogger(__name__)

# ── Safe numpy import ─────────────────────────────────────────
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logger.warning("numpy not available")

# ── pgvector import ───────────────────────────────────────────
try:
    from pgvector.django import VectorField, HnswIndex
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False
    logger.warning("pgvector not available - vector search disabled")


class SyllabusEmbedding(models.Model):
    """
    Stores vector embeddings for syllabus content in PostgreSQL.
    """
    CONTENT_TYPES = [
        ('TOPIC', 'Syllabus Topic'),
        ('OBJECTIVE', 'Learning Objective'),
        ('KNOWLEDGE', 'Knowledge Base Item'),
        ('EXAMPLE', 'Worked Example'),
        ('PAST_QUESTION', 'Past Exam Question'),
    ]

    content_type = models.CharField(max_length=20, choices=CONTENT_TYPES)
    content_text = models.TextField()

    # Vector field - dimensions must match your embedding model
    # OpenAI text-embedding-3-small = 1536
    # all-MiniLM-L6-v2 = 384
    if PGVECTOR_AVAILABLE:
        embedding = VectorField(dimensions=1536, null=True, blank=True)
    else:
        # Fallback: store as text if pgvector not available
        embedding = models.TextField(null=True, blank=True)

    # Metadata fields
    subject = models.CharField(max_length=100, db_index=True)
    stage = models.CharField(max_length=100, db_index=True)
    stage_type = models.CharField(max_length=20, db_index=True)
    unit_title = models.CharField(max_length=200, blank=True)
    topic_title = models.CharField(max_length=200, blank=True)
    difficulty = models.CharField(max_length=10, blank=True)
    cognitive_level = models.CharField(max_length=20, blank=True)

    # FK references
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
        default='text-embedding-3-small'
    )
    embedding_dimensions = models.IntegerField(default=1536)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Syllabus Embedding"
        verbose_name_plural = "Syllabus Embeddings"

    def __str__(self):
        return (
            f"[{self.content_type}] "
            f"{self.subject} - {self.topic_title[:50]}"
        )

    @classmethod
    def cosine_search(
        cls,
        query_embedding,
        subject=None,
        stage_type=None,
        content_types=None,
        limit=5,
        min_similarity=0.3,
    ):
        """Semantic search using pgvector cosine similarity."""
        if not PGVECTOR_AVAILABLE:
            logger.warning("pgvector not available, returning empty results")
            return cls.objects.none()

        from pgvector.django import CosineDistance

        qs = cls.objects.all()

        if subject:
            qs = qs.filter(subject__iexact=subject)
        if stage_type:
            qs = qs.filter(stage_type=stage_type)
        if content_types:
            qs = qs.filter(content_type__in=content_types)

        max_distance = 1 - min_similarity

        return (
            qs
            .annotate(distance=CosineDistance('embedding', query_embedding))
            .filter(distance__lte=max_distance)
            .order_by('distance')
            [:limit]
        )

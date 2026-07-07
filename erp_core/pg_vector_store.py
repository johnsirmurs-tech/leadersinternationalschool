import os
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Generates embeddings.
    Defaults to OpenAI (low RAM, works on Railway free tier).
    Falls back gracefully if API key not set.
    """

    def __init__(self):
        self.provider = os.environ.get(
            'EMBEDDING_PROVIDER', 'openai'
        )
        self.model_name = os.environ.get(
            'EMBEDDING_MODEL', 'text-embedding-3-small'
        )
        self.dimensions = int(
            os.environ.get('EMBEDDING_DIMENSIONS', '1536')
        )

    def get_embedding(self, text: str) -> List[float]:
        """Generate embedding for text."""
        if not text or not text.strip():
            return [0.0] * self.dimensions

        if self.provider == 'openai':
            return self._openai_embedding(text)
        elif self.provider == 'sentence_transformer':
            return self._local_embedding(text)
        else:
            # Return zero vector as fallback
            logger.warning(
                f"Unknown embedding provider: {self.provider}"
            )
            return [0.0] * self.dimensions

    def _openai_embedding(self, text: str) -> List[float]:
        """OpenAI embeddings - very low RAM usage."""
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key:
            logger.warning(
                "OPENAI_API_KEY not set, returning zero vector"
            )
            return [0.0] * self.dimensions

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            text = text.replace('\n', ' ').strip()[:8000]
            response = client.embeddings.create(
                model=self.model_name,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"OpenAI embedding failed: {e}")
            return [0.0] * self.dimensions

    def _local_embedding(self, text: str) -> List[float]:
        """
        Local sentence-transformers embedding.
        WARNING: Uses ~1.5GB RAM - not suitable for Railway free tier.
        """
        try:
            from sentence_transformers import SentenceTransformer
            if not hasattr(self, '_model'):
                logger.info(f"Loading model: {self.model_name}")
                self._model = SentenceTransformer(self.model_name)
            embedding = self._model.encode(
                text, normalize_embeddings=True
            )
            return embedding.tolist()
        except ImportError:
            logger.error(
                "sentence-transformers not installed. "
                "Use EMBEDDING_PROVIDER=openai instead."
            )
            return [0.0] * self.dimensions
        except Exception as e:
            logger.error(f"Local embedding failed: {e}")
            return [0.0] * self.dimensions

    def get_embeddings_batch(
        self, texts: List[str]
    ) -> List[List[float]]:
        """Batch embedding generation."""
        return [self.get_embedding(t) for t in texts]

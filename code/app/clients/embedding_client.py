from functools import lru_cache

from app.core.config import get_settings


class EmbeddingClient:
    def __init__(self) -> None:
        settings = get_settings()
        from sentence_transformers import SentenceTransformer

        self.model_id = settings.embedding_model
        self.model = SentenceTransformer(settings.embedding_path or self.model_id, device="cpu")
        dimension = self.model.get_sentence_embedding_dimension()
        if dimension != settings.embedding_dim:
            raise ValueError("EMBEDDING_DIM does not match the loaded model")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        for text in texts:
            token_count = len(
                self.model.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"]
            )
            if token_count > self.model.max_seq_length:
                raise ValueError(
                    f"Text has {token_count} tokens; split below {self.model.max_seq_length} tokens"
                )
        return self.model.encode(texts, normalize_embeddings=True, batch_size=16).tolist()

    def embed_query(self, query: str) -> list[float]:
        prefix = "为这个句子生成表示以用于检索相关文章："
        return self.embed_texts([prefix + query])[0]


@lru_cache
def get_embedding_client() -> EmbeddingClient:
    return EmbeddingClient()

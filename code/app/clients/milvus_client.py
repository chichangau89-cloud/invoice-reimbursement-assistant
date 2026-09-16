from pymilvus import DataType, MilvusClient

from app.core.config import get_settings
from app.core.ids import validate_key


class MilvusVectorClient:
    def __init__(self) -> None:
        settings = get_settings()
        validate_key(settings.milvus_collection, "MILVUS_COLLECTION")
        self.collection_name = settings.milvus_collection
        self.dimension = settings.embedding_dim
        self.client = MilvusClient(
            uri=settings.milvus_uri,
            token=settings.milvus_token,
            timeout=60,
        )

    def close(self) -> None:
        self.client.close()

    def ensure_collection(self) -> None:
        if not self.client.has_collection(collection_name=self.collection_name):
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
            for field, length in (
                ("tenant_id", 64),
                ("doc_type", 32),
                ("source_id", 512),
                ("source_version", 128),
                ("title", 600),
                ("content", 6000),
                ("content_hash", 64),
                ("embedding_model", 128),
            ):
                schema.add_field(field_name=field, datatype=DataType.VARCHAR, max_length=length)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=self.dimension)
            indexes = self.client.prepare_index_params()
            indexes.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=indexes,
                consistency_level="Strong",
            )
        fields = self.client.describe_collection(collection_name=self.collection_name)["fields"]
        vector = next(field for field in fields if field["name"] == "vector")
        if int(vector["params"]["dim"]) != self.dimension:
            raise ValueError("Existing Milvus collection has a different vector dimension")
        self.client.load_collection(collection_name=self.collection_name)

    def upsert(self, documents: list[dict]) -> None:
        self.ensure_collection()
        self.client.upsert(collection_name=self.collection_name, data=documents)

    def search(self, vector: list[float], tenant_id: str, doc_type: str, limit: int) -> list[dict]:
        self.ensure_collection()
        hits = self.client.search(
            collection_name=self.collection_name,
            data=[vector],
            anns_field="vector",
            filter=f'tenant_id == "{tenant_id}" and doc_type == "{doc_type}"',
            limit=limit,
            output_fields=["content_hash", "embedding_model"],
            search_params={"metric_type": "COSINE", "params": {}},
            consistency_level="Strong",
        )
        return list(hits[0])

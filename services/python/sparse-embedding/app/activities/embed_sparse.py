import json
import logging
from typing import Literal

from fastembed import SparseEmbedding
from pydantic import BaseModel
from temporalio import activity
from tokenizers import Tokenizer

from app.model_manager import model_manager

logger = logging.getLogger(__name__)


class EmbedSparseParams(BaseModel):
    userProfileId: str
    emailId: str
    translatedSubject: str | None = None
    translatedBody: str
    summarizedBody: str | None = None
    chunks: list[str]

class SparseVector(BaseModel):
    indices: list[int]
    values: list[float]

class PointInput(BaseModel):
    emailId: str
    vector: list[float]
    sparseVector: SparseVector | None = None
    pointType: Literal['chunk', 'summary', 'full']
    index: int

CHUNK_SIZE = 3_200

def get_tokens_and_weights(sparse_embedding: SparseEmbedding, tokenizer: Tokenizer) -> dict[str, float]:
    token_weight_dict: dict[str, float] = {}
    for i in range(len(sparse_embedding.indices)):
        token: str = tokenizer.decode([sparse_embedding.indices[i]])  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        weight: float = float(sparse_embedding.values[i])  # pyright: ignore[reportAny]
        token_weight_dict[token] = weight

    return dict(sorted(token_weight_dict.items(), key=lambda item: item[1], reverse=True))

@activity.defn(name="embedSparse")
async def embed_sparse(params: EmbedSparseParams) -> list[PointInput]:
    user_profile_id: str = params.userProfileId
    email_id: str = params.emailId
    translatedSubject: str | None = params.translatedSubject
    translatedBody: str = params.translatedBody
    summarizedBody: str | None = params.summarizedBody
    chunks: list[str] = params.chunks

    logger.info(
        f"Generating SPLADE vectors for email {email_id} for user {user_profile_id}"
    )

    documents: list[str] = []
    point_inputs: list[PointInput] = []

    if summarizedBody:
        content = f"Subject: {translatedSubject}\n\nSummary: {summarizedBody}"
        documents.append(content)
        point_inputs.append(PointInput(emailId=email_id, vector=[], pointType="summary", index=0))
    else:
        content = f"Subject: {translatedSubject}\n\nBody: {translatedBody}"
        documents.append(content)
        point_inputs.append(PointInput(emailId=email_id, vector=[], pointType="full", index=0))

    if len(chunks) > 1:
        for i, chunk in enumerate(chunks):
            documents.append(chunk)
            point_inputs.append(PointInput(
                emailId=email_id,
                vector=[],
                pointType="chunk",
                index=i
            ))

    if not documents:
        logger.warning("Email has no documents to embed, skipping")
        return []

    model = model_manager.get_model()
    embeddings: list[SparseEmbedding] = list(model.embed(documents))

    tokenizer: Tokenizer = Tokenizer.from_pretrained("Qdrant/Splade_PP_en_v1")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    token_weights: dict[str, float] = get_tokens_and_weights(embeddings[0], tokenizer)  # pyright: ignore[reportUnknownArgumentType]
    logger.debug(f"Token weights for first document: {json.dumps(token_weights, indent=4)}")

    for i, embedding in enumerate(embeddings):
        point_inputs[i].sparseVector = SparseVector(
            indices=[int(idx) for idx in embedding.indices],  # pyright: ignore[reportAny]
            values=[float(val) for val in embedding.values]  # pyright: ignore[reportAny]
        )

    logger.info(f"Generated {len(embeddings)} sparse vectors for email {email_id}")
    return point_inputs


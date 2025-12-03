import logging
from concurrent import futures

import grpc

from app.model_manager import model_manager
from proto import sparse_embedding_pb2, sparse_embedding_pb2_grpc  # pyright: ignore[reportImplicitRelativeImport]

logger = logging.getLogger(__name__)


class SparseEmbeddingServicer(sparse_embedding_pb2_grpc.SparseEmbeddingServiceServicer):
    def embedQuery(  # pyright: ignore[reportImplicitOverride]
        self,
        request: sparse_embedding_pb2.EmbedQueryRequest,
        context: grpc.ServicerContext,
    ) -> sparse_embedding_pb2.EmbedQueryResponse:
        try:
            logger.info(f"Generating sparse embedding for query: {request.query[:50]}...")

            embedding_model = model_manager.get_model()
            embeddings = list(embedding_model.embed([request.query]))

            if not embeddings or len(embeddings) == 0:
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("Failed to generate embedding")
                return sparse_embedding_pb2.EmbedQueryResponse()

            embedding = embeddings[0]
            sparse_vector = sparse_embedding_pb2.SparseVector(
                indices=[int(idx) for idx in embedding.indices],  # pyright: ignore[reportAny]
                values=[float(val) for val in embedding.values],  # pyright: ignore[reportAny]
            )

            logger.info(f"Generated sparse embedding with {len(sparse_vector.indices)} dimensions")

            return sparse_embedding_pb2.EmbedQueryResponse(sparseVector=sparse_vector)

        except Exception as e:
            logger.error(f"Error generating sparse embedding: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error generating sparse embedding: {str(e)}")
            return sparse_embedding_pb2.EmbedQueryResponse()


async def serve_grpc(port: int = 50051) -> None:
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    sparse_embedding_pb2_grpc.add_SparseEmbeddingServiceServicer_to_server(  # pyright: ignore[reportUnknownMemberType]
        SparseEmbeddingServicer(), server
    )
    server.add_insecure_port(f"[::]:{port}")  # pyright: ignore[reportUnusedCallResult]
    await server.start()
    logger.info(f"gRPC server started on port {port}")
    await server.wait_for_termination()  # pyright: ignore[reportUnusedCallResult]


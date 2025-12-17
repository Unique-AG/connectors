import logging
from fastembed import SparseTextEmbedding

logger = logging.getLogger(__name__)


class ModelManager:
    _instance: "ModelManager | None" = None
    _model: SparseTextEmbedding | None = None

    def __new__(cls) -> "ModelManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_model(self) -> SparseTextEmbedding:
        if self._model is None:
            logger.info("Loading SPLADE model...")
            self._model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")
            logger.info("SPLADE model loaded successfully")
        return self._model


model_manager = ModelManager()


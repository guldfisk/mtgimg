from __future__ import annotations

import typing as t

from concurrent.futures import Executor, ThreadPoolExecutor

from PIL import Image
from promise import Promise

from mtgimg.base import BaseImageLoader
from mtgimg.interface import (
    ImageRequest,
    Imageable,
)
from mtgimg import pipeline


class Loader(BaseImageLoader):

    def __init__(
        self,
        printing_executor: t.Union[Executor, int] = None,
        imageable_executor: t.Union[Executor, int] = None,
        *,
        image_cache_size: t.Optional[int] = 64,
    ):
        super().__init__(image_cache_size = image_cache_size)

        self._printings_executor = (
            printing_executor
            if isinstance(printing_executor, Executor) else
            ThreadPoolExecutor(
                max_workers = printing_executor if isinstance(printing_executor, int) else 8
            )
        )

        self._imageables_executor = (
            imageable_executor
            if isinstance(imageable_executor, Executor) else
            ThreadPoolExecutor(
                max_workers = imageable_executor if isinstance(imageable_executor, int) else 4
            )
        )

    def _get_image(self, image_request: ImageRequest = None) -> Promise[Image.Image]:
        return Promise.resolve(
            (
                self._imageables_executor
                if isinstance(image_request.pictured, Imageable) else
                self._printings_executor
            ).submit(
                pipeline.get_pipeline(image_request).get_image,
                image_request,
                self,
            )
        )

    def stop(self) -> None:
        self._imageables_executor.shutdown(wait = False)
        self._printings_executor.shutdown(wait = False)

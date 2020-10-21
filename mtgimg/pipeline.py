from __future__ import annotations

import typing as t
import os

from abc import ABC, abstractmethod

from PIL import Image

from yeetlong.taskawaiter import TaskAwaiter, EventWithValue

from mtgimg.fetch import get_scryfall_image
from mtgimg.interface import (
    ImageRequest,
    ImageLoader,
    ImageFetchException,
    SizeSlug,
    resize_image, Imageable,
)
from mtgimg import crop as image_crop


class ImageSource(ABC):

    @abstractmethod
    def get_image(self, image_request: ImageRequest, loader: ImageLoader) -> Image.Image:
        pass


class ImageableProcessor(ImageSource):
    _processing: TaskAwaiter[ImageRequest, Image.Image] = TaskAwaiter()

    @classmethod
    def get_imageable_image(
        cls,
        image_request: ImageRequest,
        size: t.Tuple[int, int],
        loader: ImageLoader,
        event: EventWithValue[ImageRequest, Image.Image],
    ) -> t.Optional[Image.Image]:
        image = image_request.pictured.get_image(
            size,
            loader,
            image_request.back,
            image_request.crop,
        )

        if image.size != size:
            image = image.resize(size, Image.LANCZOS)

        if image_request.save:
            if not os.path.exists(image_request.dir_path):
                os.makedirs(image_request.dir_path)

            image.save(image_request.path)

        if image_request.cache_only:
            event.set_value(None)
            return

        event.set_value(image)
        return image

    @classmethod
    def get_image(cls, image_request: ImageRequest, loader: ImageLoader) -> t.Optional[Image.Image]:
        if image_request.allow_disk_cached:
            if image_request.cache_only:
                if os.path.exists(image_request.path):
                    return
            else:
                try:
                    return loader.load_image_from_disk(image_request.path)
                except ImageFetchException:
                    pass
        elif image_request.cache_only:
            return None

        event, in_progress = cls._processing.get_condition(image_request)

        if in_progress:
            event.wait()
            return event.value

        return cls.get_imageable_image(
            image_request,
            image_request.size_slug.get_size(
                image_request.crop
            ),
            loader,
            event,
        )


class Fetcher(ImageSource):
    _fetching: TaskAwaiter[ImageRequest, Image.Image] = TaskAwaiter()

    @classmethod
    def _fetch_image(cls, event: EventWithValue[ImageRequest, Image.Image], image_request: ImageRequest):
        with event:
            fetched_image = get_scryfall_image(image_request)

            if image_request.save:
                fetched_image.save(
                    image_request.path,
                    image_request.extension,
                )

            event.set_value(fetched_image)

            return fetched_image

    @classmethod
    def get_image(cls, image_request: ImageRequest, loader: ImageLoader) -> Image.Image:
        if image_request.allow_disk_cached:
            try:
                return loader.load_image_from_disk(image_request.path)
            except ImageFetchException:
                if image_request.pictured_name:
                    raise ImageFetchException('No local image with that name')
                elif not image_request.has_image:
                    raise ImageFetchException('Missing default image')

        event, in_progress = cls._fetching.get_condition(image_request)

        if in_progress:
            event.wait()
            return event.value

        return cls._fetch_image(event, image_request)


class ImageTransformer(ImageSource):
    _tasks: TaskAwaiter[ImageRequest, Image.Image] = None

    def __init__(self, source: t.Union[ImageSource, t.Type[ImageSource]]):
        self._source = source

    @abstractmethod
    def _process_image(self, image: Image.Image, image_request: ImageRequest) -> Image.Image:
        pass

    @abstractmethod
    def _spawn_image_request(self, image_request: ImageRequest) -> ImageRequest:
        pass

    def get_image(self, image_request: ImageRequest, loader: ImageLoader) -> Image.Image:
        if image_request.allow_disk_cached:
            try:
                return loader.load_image_from_disk(image_request.path)
            except ImageFetchException:
                pass

        event, in_progress = self._tasks.get_condition(image_request)

        if in_progress:
            event.wait()
            return event.value

        with event:
            source_image = self._source.get_image(
                self._spawn_image_request(image_request),
                loader,
            )

            processed_image = self._process_image(
                source_image,
                image_request,
            )

            if image_request.save:
                if not os.path.exists(image_request.dir_path):
                    os.makedirs(image_request.dir_path)
                processed_image.save(image_request.path, image_request.extension)

            event.set_value(processed_image)

            return processed_image

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self._source})'


class Cropper(ImageTransformer):
    _tasks = TaskAwaiter()

    def _process_image(self, image: Image.Image, image_request: ImageRequest) -> Image.Image:
        return image_crop.crop(image, image_request)

    def _spawn_image_request(self, image_request: ImageRequest) -> ImageRequest:
        return image_request.spawn(crop = False)


class ReSizer(ImageTransformer):
    _tasks = TaskAwaiter()

    def _process_image(self, image: Image.Image, image_request: ImageRequest) -> Image.Image:
        return resize_image(
            image = image,
            size_slug = image_request.size_slug,
            crop = image_request.crop
        )

    def _spawn_image_request(self, image_request: ImageRequest) -> ImageRequest:
        return image_request.spawn(size_slug = SizeSlug.ORIGINAL)


class CacheOnly(ImageSource):

    def __init__(self, source: t.Union[ImageSource, t.Type[ImageSource]]):
        self._source = source

    def get_image(self, image_request: ImageRequest, loader: ImageLoader) -> None:
        self._source.get_image(image_request, loader)
        return None


def get_pipeline(image_request: ImageRequest) -> t.Union[t.Type[ImageSource], ImageSource]:
    if isinstance(image_request.pictured, Imageable):
        return ImageableProcessor

    _pipeline = Fetcher

    if image_request.crop:
        _pipeline = Cropper(_pipeline)

    if image_request.size_slug != SizeSlug.ORIGINAL:
        _pipeline = ReSizer(_pipeline)

    if image_request.cache_only:
        _pipeline = CacheOnly(_pipeline)

    return _pipeline

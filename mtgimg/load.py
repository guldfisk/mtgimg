from __future__ import annotations

import copy
import io
import typing as t

import os
from concurrent.futures import Executor, ThreadPoolExecutor
from threading import Lock, Event
from abc import ABC, abstractmethod

import requests as r
from PIL import Image
from promise import Promise

from mtgorp.models.persistent.attributes.layout import Layout
from mtgorp.models.persistent.printing import Printing

from mtgimg import paths
from mtgimg.interface import (
    ImageRequest,
    Imageable,
    ImageLoader,
    pictureable,
    ImageFetchException,
    SizeSlug,
)
from mtgimg import crop as image_crop


T = t.TypeVar('T')


class EventWithValue(Event, t.Generic[T]):

    def __init__(self, task_awaiter: TaskAwaiter, key: ImageRequest) -> None:
        super().__init__()
        self._task_awaiter = task_awaiter
        self._key = key
        self.value: t.Union[None, T, Exception] = None

    def set_value(self, value: t.Union[T, Exception]) -> None:
        self.value = value
        self._task_awaiter.del_key(self._key)
        super().set()

    def set(self) -> None:
        raise NotImplemented()


class TaskAwaiter(t.Generic[T]):

    def __init__(self):
        self._lock = Lock()
        self._map: t.Dict[ImageRequest, EventWithValue[T]] = {}

    def del_key(self, image_request: ImageRequest) -> None:
        with self._lock:
            del self._map[image_request]

    def get_condition(self, image_request: ImageRequest) -> t.Tuple[EventWithValue[T], bool]:
        with self._lock:
            try:
                return self._map[image_request], True
            except KeyError:
                self._map[image_request] = event = EventWithValue(self, image_request)
                return event, False


class _ImageableProcessor(object):
    _processing: TaskAwaiter[Image.Image] = TaskAwaiter()

    @classmethod
    def get_imageable_image(
        cls,
        image_request: ImageRequest,
        size: t.Tuple[int, int],
        loader: ImageLoader,
        event: EventWithValue[Image.Image],
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
    def get_image(cls, image_request: ImageRequest, loader: ImageLoader):
        if image_request.cache_only:
            if os.path.exists(image_request.path):
                return
        else:
            try:
                return loader.open_image(image_request.path)
            except ImageFetchException:
                pass

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


class PrintingSource(ABC):

    @abstractmethod
    def get_image(self, image_request: ImageRequest, loader: ImageLoader) -> Image.Image:
        pass


class _Fetcher(PrintingSource):
    _fetching: TaskAwaiter[Image.Image] = TaskAwaiter()
    _size = SizeSlug.ORIGINAL.get_size()

    @classmethod
    def _fetch_image(cls, event: EventWithValue[Image.Image], image_request: ImageRequest):
        try:
            remote_card_response = r.request('GET', image_request.remote_card_uri, timeout = 30)
        except Exception as e:
            raise ImageFetchException(e)

        if not remote_card_response.ok:
            raise ImageFetchException(remote_card_response.status_code)

        remote_card = remote_card_response.json()

        try:
            if image_request.pictured.cardboard.layout == Layout.MELD and image_request.back:
                for part in remote_card['all_parts']:
                    if part['name'] == image_request.pictured.cardboard.back_card.name:
                        remote_card = r.request('GET', part['uri'], timeout = 30).json()

            image_response = r.request(
                'GET',
                remote_card['card_faces'][-1 if image_request.back else 0]['image_uris']['png']
                if image_request.pictured.cardboard.layout == Layout.TRANSFORM else
                remote_card['image_uris']['png'],
                stream = True,
                timeout = 30,
            )

        except Exception as e:
            raise ImageFetchException(e)

        if not image_response.ok:
            raise ImageFetchException(remote_card_response.status_code)

        if not os.path.exists(image_request.dir_path):
            os.makedirs(image_request.dir_path)

        with io.BytesIO() as download_file:
            for chunk in image_response.iter_content(1024):
                download_file.write(chunk)

            fetched_image = Image.open(download_file)
            fetched_image.load()

        if not fetched_image.size == cls._size:
            fetched_image = fetched_image.resize(cls._size, Image.LANCZOS)

        fetched_image.save(
            image_request.path,
            image_request.extension,
        )

        event.set_value(fetched_image)

        return fetched_image

    @classmethod
    def get_image(cls, image_request: ImageRequest, loader: ImageLoader) -> Image.Image:
        try:
            return loader.open_image(image_request.path)
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


class ImageTransformer(PrintingSource):
    _tasks: TaskAwaiter[Image.Image] = None

    def __init__(self, source: t.Union[PrintingSource, t.Type[PrintingSource]]):
        self._source = source

    @abstractmethod
    def _process_image(self, image: Image.Image, image_request: ImageRequest) -> Image.Image:
        pass

    @abstractmethod
    def _spawn_image_request(self, image_request: ImageRequest) -> ImageRequest:
        pass

    def get_image(self, image_request: ImageRequest, loader: ImageLoader) -> Image.Image:
        try:
            return loader.open_image(image_request.path)
        except ImageFetchException:
            pass

        event, in_progress = self._tasks.get_condition(image_request)

        if in_progress:
            event.wait()
            if isinstance(event.value, Exception):
                raise event.value
            return event.value

        try:
            source_image = self._source.get_image(
                self._spawn_image_request(image_request),
                loader,
            )
        except Exception as e:
            event.set_value(e)
            raise e

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

    @classmethod
    def resize_image(cls, image: Image.Image, size_slug: SizeSlug, crop: bool = False) -> Image.Image:
        return image.resize(
            size_slug.get_size(crop),
            Image.LANCZOS,
        )

    def _process_image(self, image: Image.Image, image_request: ImageRequest) -> Image.Image:
        return self.resize_image(
            image = image,
            size_slug = image_request.size_slug,
            crop = image_request.crop
        )

    def _spawn_image_request(self, image_request: ImageRequest) -> ImageRequest:
        return image_request.spawn(size_slug = SizeSlug.ORIGINAL)


class Loader(ImageLoader):

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
            if printing_executor is isinstance(printing_executor, Executor) else
            ThreadPoolExecutor(
                max_workers = printing_executor if isinstance(printing_executor, int) else 10
            )
        )

        self._imageables_executor = (
            imageable_executor
            if imageable_executor is isinstance(imageable_executor, Executor) else
            ThreadPoolExecutor(
                max_workers = imageable_executor if isinstance(imageable_executor, int) else 10
            )
        )

    def get_image(
        self,
        pictured: pictureable = None,
        *,
        pictured_type: t.Union[t.Type[Printing], t.Type[Imageable]] = Printing,
        picture_name: t.Optional[str] = None,
        back: bool = False,
        crop: bool = False,
        size_slug: SizeSlug = SizeSlug.ORIGINAL,
        save: bool = True,
        cache_only: bool = False,
        image_request: ImageRequest = None,
    ) -> Promise[Image.Image]:
        _image_request = (
            ImageRequest(
                pictured = pictured,
                pictured_type = pictured_type,
                picture_name = picture_name,
                back = back,
                crop = crop,
                size_slug = size_slug,
                save = save,
                cache_only = cache_only,
            )
            if image_request is None else
            image_request
        )

        if isinstance(_image_request.pictured, Imageable):
            return Promise.resolve(
                self._imageables_executor.submit(
                    _ImageableProcessor.get_image,
                    _image_request,
                    self,
                )
            )

        pipeline = _Fetcher

        if _image_request.crop:
            pipeline = Cropper(pipeline)

        if _image_request.size_slug != SizeSlug.ORIGINAL:
            pipeline = ReSizer(pipeline)

        return Promise.resolve(
            self._printings_executor.submit(
                pipeline.get_image,
                _image_request,
                self,
            )
        )

    _size_cardback_path_map = {
        SizeSlug.ORIGINAL: paths.CARD_BACK_PATH,
        SizeSlug.MEDIUM: paths.MEDIUM_CARD_BACK_PATH,
        SizeSlug.SMALL: paths.SMALL_CARD_BACK_PATH,
        SizeSlug.THUMBNAIL: paths.THUMBNAIL_CARD_BACK_PATH,
    }

    def get_default_image(self, size_slug: SizeSlug = SizeSlug.ORIGINAL) -> Image.Image:
        try:
            return self.open_image(
                self._size_cardback_path_map[size_slug]
            )
        except ImageFetchException:
            resized_back = ReSizer.resize_image(
                self.open_image(
                    self._size_cardback_path_map[SizeSlug.ORIGINAL]
                ),
                size_slug,
                False,
            )
            with open(self._size_cardback_path_map[size_slug], 'wb') as f:
                resized_back.save(f)

            return resized_back
